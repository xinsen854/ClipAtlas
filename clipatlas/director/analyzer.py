"""One-shot API director analysis: S/A/B grading of a finalised script.

Per the agreed architecture this is one of only two API call sites in the
whole rough-cut pipeline (the other is catalog annotation at ingest time).
The result is cached permanently against (script hash, prompt version,
rules revision) so re-planning never calls the API again.
"""

import json
from hashlib import sha256
from typing import Any, cast

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from clipatlas.director.models import DirectorAnalysis, DirectorUnit
from clipatlas.director.requirements import (
    RequirementDraft,
    materialize_requirements,
    parse_script_visual_requirements,
)
from clipatlas.domain.visual_protocol import PROTOCOL_VERSION
from clipatlas.providers.errors import (
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderRequestError,
)

DEFAULT_MODEL = "qwen3.8-flash"
DIRECTOR_PROMPT_VERSION = "director-v6-shared-visual-schema"
DEFAULT_RULES_REVISION = "roughcut-matching-rules-2026-09"

_DIRECTOR_SYSTEM_PROMPT = (
    "You are the director-analysis layer of an automatic rough-cut system. "
    "You grade one finished narration script into S/A/B content units. "
    "S (selling point): a core claim that needs a directly matching shot; it may span "
    "one to three sentences and must NOT be split into per-sentence fragments. "
    "A (evidence): parameters, principles, background, data or further explanation; a "
    "reasonable substitute is acceptable. "
    "B (connective): transitions, emphasis or filler with no independent visual content; "
    "B never creates its own search task. "
    "Every unit MUST include an 'importance' field with exactly one value: \"S\", \"A\" or \"B\". "
    "For every unit also return: text_range (the exact quoted span from the script); "
    "topic (short); subtopics (optional); required_subjects / required_objects / "
    "required_actions (camera-observable, checkable against real footage — do not invent "
    "a test event the script never says was filmed); acceptable_surrogates (views that "
    "fairly represent the requirement); avoid (visually wrong substitutes that must never "
    "be used); visual_function (one sentence of purpose); anchor_phrase (the key spoken "
    "phrase the direct evidence must align with, if importance is S or A). "
    "For every S or A unit also return must_have and preferred. must_have contains only "
    "1 to 4 minimal atomic visual facts that are indispensable to prove this exact spoken "
    "claim. Every item must name one observable subject, object, action, scene, OCR phrase "
    "or numeric fact. Never combine alternatives with slash, 'or', parentheses or examples. "
    "Do not require a venue, camera device or ceremonial action unless the narration itself "
    "claims that exact fact. preferred contains optional supporting details and must never "
    "be required for a DIRECT match. For B units both lists must be empty. "
    "Cover the whole script in order. Do not add units for material not in the script. "
    "All descriptive values MUST be written in Simplified Chinese, including topic, "
    "subtopics, required_subjects, required_objects, required_actions, "
    "acceptable_surrogates, avoid and visual_function. Preserve model names, brand "
    "names and technical abbreviations from the script exactly, such as ADS, NOA, "
    "AEB and L2. Do not translate Chinese entities into English. "
    "Output ONLY a single JSON object matching this exact shape: "
    '{"units": [{"importance": "S", "text_range": "...", "topic": "...", '
    '"subtopics": [], "required_subjects": [], "required_objects": [], '
    '"required_actions": [], "acceptable_surrogates": [], "must_have": [], '
    '"preferred": [], "avoid": [], '
    '"visual_function": "...", "anchor_phrase": "..."}]}. '
    "No prose before or after the JSON."
)


class _DirectorPayload(BaseModel):
    # AI 结构化输出偶会附带未要求的附加字段，忽略多余字段而不是让整条文案导演解析失败。
    model_config = ConfigDict(extra="ignore")

    units: list[DirectorUnit] = Field(default_factory=list)
    requirements: list[RequirementDraft] = Field(default_factory=list)


def _strict_json_schema() -> dict[str, Any]:
    schema = _DirectorPayload.model_json_schema()

    def visit(node: object) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" or "properties" in node:
                node["additionalProperties"] = False
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(schema)
    return schema


def _infer_importance(text_range: str) -> str:
    """Local fallback when the model omits the importance field."""
    if any(
        marker in text_range
        for marker in (
            "第一道",
            "第二道",
            "第三道",
            "三道考题",
            "立旗帜",
            "立标准",
            "立品质",
            "立一个时代",
            "最终答案",
            "核心",
            "才是",
            "不是流量",
        )
    ):
        return "S"
    if any(marker in text_range for marker in ("%", "兆帕", "参数", "配置", "原理", "技术支撑", "实测", "数据")):
        return "A"
    return "B"


def _repair_units(decoded: dict[str, Any]) -> list[DirectorUnit] | None:
    """Rebuild a units list that failed strict validation, filling missing fields."""
    raw_units = decoded.get("units")
    if not isinstance(raw_units, list) or not raw_units:
        return None
    repaired: list[dict[str, Any]] = []
    for raw in raw_units:
        if not isinstance(raw, dict):
            return None
        item = dict(raw)
        if not isinstance(item.get("importance"), str):
            item["importance"] = _infer_importance(str(item.get("text_range", "")))
        if not isinstance(item.get("topic"), str) or not item["topic"].strip():
            item["topic"] = "未命名内容单元"
        repaired.append(item)
    try:
        return _DirectorPayload.model_validate({"units": repaired}).units
    except (ValueError, TypeError, ValidationError):
        return None


def _coerce_json_object(content: str) -> dict[str, Any] | None:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("```", 2)[1] if stripped.count("```") >= 2 else stripped[3:]
        stripped = stripped.strip()
        if stripped.startswith("json"):
            stripped = stripped[4:].lstrip()
    try:
        decoded = json.loads(stripped)
        if isinstance(decoded, dict):
            return decoded
    except ValueError:
        pass
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        decoded = json.loads(stripped[start : end + 1])
    except ValueError:
        return None
    return decoded if isinstance(decoded, dict) else None


def script_hash(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


class DirectorAnalyzer:
    """OpenAI-compatible one-shot analyzer; one call per finalised script."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str = DEFAULT_MODEL,
        prompt_version: str = DIRECTOR_PROMPT_VERSION,
        rules_revision: str = DEFAULT_RULES_REVISION,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        if not api_key.strip():
            raise ValueError("api_key is required")
        if not base_url.strip():
            raise ValueError("base_url is required")
        if not model.strip():
            raise ValueError("model is required")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._api_key = api_key.strip()
        self._base_url = base_url.strip().rstrip("/")
        self._model = model.strip()
        self._prompt_version = prompt_version
        self._rules_revision = rules_revision
        self._client = client
        self._timeout_seconds = timeout_seconds

    def _request_body(self, script_text: str, rules_text: str = "") -> dict[str, Any]:
        from clipatlas.director.contract import DIRECTOR_CONTRACT_PROMPT
        schema = _strict_json_schema()
        return {
            "model": self._model,
            "enable_thinking": False,
            "messages": [
                {"role": "system", "content": (
                    "Analyze the entire narration once. Return JSON {units: [...], requirements: [...]}. "
                    "Each unit needs text_range (exact quote), importance (S|A|B), topic, "
                    "visual_goal and claims. S: core selling point, A: explanation or background, "
                    "B: connective narration. Keep script order and cover the whole narration. "
                    "Create visual requirements from complete sentence meaning; comma/semicolon clauses "
                    "may carry sub-requirements, but they are NOT automatic shot cuts. Prefer one continuous "
                    "shot for one complete sentence whenever one legal source window can cover it. "
                    "Each requirement must keep an exact source_quote and use the SAME semantic axes as the "
                    "video timeline: subject, action, scene, environment, objects, configurations, quantities, "
                    "relations and state_changes. Also return temporal_relation, same-subject/continuity needs, "
                    "proof_expressions, related_expressions, generic_expressions, must_have, preferred, avoid, "
                    "importance, candidate_scope and anchor_phrase. anchor_phrase must be an exact substring of "
                    "source_quote and should identify the spoken S/A phrase whose strongest local evidence should "
                    "appear at the same time. Use Simplified Chinese for ALL semantic prose and labels. Preserve "
                    "brand/model names and technical acronyms exactly (for example 泰钽700, BJ40, ADS, NOA, AEB). "
                    "Do not translate Chinese semantics into English. Do not supply legacy required_* or must_have "
                    "fields inside unit claims when structured claims are present. "
                    + DIRECTOR_CONTRACT_PROMPT
                )},
                {
                    "role": "user",
                    "content": f"Project editing rules:\n{rules_text or '(none)'}\n\nFinished narration script:\n{script_text}",
                },
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "clipatlas_director_analysis",
                    "strict": True,
                    "schema": schema,
                },
            },
        }

    async def analyze(
        self, script_text: str, rules_revision: str | None = None,
        *, rules_text: str = "",
    ) -> DirectorAnalysis:
        if not script_text.strip():
            return self._empty_analysis(script_text)

        payload = self._request_body(script_text, rules_text)
        if self._client is not None:
            content = await self._post_content(self._client, payload)
        else:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                content = await self._post_content(client, payload)

        validation_detail = ""
        decoded: dict[str, Any] | None = None
        try:
            decoded_object = cast(object, json.loads(content))
            if not isinstance(decoded_object, dict):
                decoded = _coerce_json_object(content)
            else:
                decoded = decoded_object
            if not isinstance(decoded, dict):
                raise ValueError("structured response must be an object")
            parsed = _DirectorPayload.model_validate(decoded)
            units = parsed.units
            requirements = materialize_requirements(script_text, parsed.requirements)
        except (ValueError, TypeError, ValidationError) as exc:
            validation_detail = str(exc).replace("\n", " ")[:800]
            units = _repair_units(decoded) if isinstance(decoded, dict) else None
            if units is None:
                raise ProviderRequestError(
                    "Director analyzer returned invalid structured output"
                    + (f": {validation_detail}" if validation_detail else "")
                ) from None
            requirements = []

        from clipatlas.director.contract import validate_unit_claims
        units = [validate_unit_claims(unit, script_text) for unit in units]
        effective_revision = rules_revision or self._rules_revision
        issues = []
        if not requirements:
            requirements = parse_script_visual_requirements(script_text)
            issues.append("Director未返回有效视觉需求，使用本地词表降级解析")
        return DirectorAnalysis(
            script_text=script_text,
            script_hash=script_hash(script_text),
            prompt_version=self._prompt_version,
            rules_revision=effective_revision,
            units=units,
            requirements=requirements,
            protocol_version=PROTOCOL_VERSION,
            api_request_count=1,
            contract_issues=issues,
        )

    def _empty_analysis(
        self, script_text: str, rules_revision: str | None = None,
    ) -> DirectorAnalysis:
        return DirectorAnalysis(
            script_text=script_text,
            script_hash=script_hash(script_text),
            prompt_version=self._prompt_version,
            rules_revision=rules_revision or self._rules_revision,
            units=[],
            requirements=parse_script_visual_requirements(script_text),
            protocol_version=PROTOCOL_VERSION,
            api_request_count=0,
        )

    async def _post_content(self, client: httpx.AsyncClient, payload: dict[str, Any]) -> str:
        try:
            response = await client.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self._timeout_seconds,
            )
        except httpx.RequestError as exc:
            raise ProviderRequestError("Director analyzer upstream request failed") from exc

        if response.status_code in {401, 403}:
            raise ProviderAuthenticationError(
                f"Director analyzer upstream returned HTTP {response.status_code}"
            )
        if response.status_code == 429:
            raise ProviderRateLimitError("Director analyzer upstream returned HTTP 429")
        if response.is_error:
            raise ProviderRequestError(
                f"Director analyzer upstream returned HTTP {response.status_code}"
            )

        try:
            return self._content_from_response(response.json())
        except ValueError as exc:
            raise ProviderRequestError("Director analyzer returned invalid JSON") from exc

    @staticmethod
    def _content_from_response(payload: object) -> str:
        if not isinstance(payload, dict):
            raise ProviderRequestError("Director analyzer returned invalid structured output")
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderRequestError("Director analyzer returned invalid structured output")
        first = choices[0]
        if not isinstance(first, dict):
            raise ProviderRequestError("Director analyzer returned invalid structured output")
        message = first.get("message")
        if not isinstance(message, dict):
            raise ProviderRequestError("Director analyzer returned invalid structured output")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ProviderRequestError("Director analyzer returned invalid structured output")
        return content

import json
from typing import Any, cast

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from clipatlas.providers.errors import (
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderRequestError,
)
from clipatlas.rules.models import ProjectRule

_DEFAULT_MODEL = "qwen3.8-flash"


class RuleAnalysisResult(BaseModel):
    source_text: str
    rules: list[ProjectRule] = Field(default_factory=list)


class _RuleAnalysisPayload(BaseModel):
    # AI 结构化输出偶会附带未要求的附加字段，忽略多余字段而不是让整条规则解析失败。
    model_config = ConfigDict(extra="ignore")

    rules: list[ProjectRule] = Field(default_factory=list)


_SYSTEM_PROMPT = (
    "You convert batch-specific user instructions into candidate ClipAtlas project rules. "
    "Return only rules explicitly supported by the user's instructions. Do not invent pronunciations, "
    "aliases, business facts, or semantic preferences. Use only these rule kinds: pronunciation, "
    "speech_suppress, speech_replace, subtitle_replace, entity_alias, semantic_hint. "
    "pronunciation, speech_replace, subtitle_replace, and entity_alias require match and replacement. "
    "speech_suppress requires match only. semantic_hint requires hint only. "
    "These are candidates only; do not claim they are active or applied."
)


class QwenRuleAnalyzer:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str = _DEFAULT_MODEL,
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
        self._client = client
        self._timeout_seconds = timeout_seconds

    async def analyze(self, source_text: str) -> RuleAnalysisResult:
        if not source_text.strip():
            return RuleAnalysisResult(source_text=source_text)

        payload = self._request_body(source_text)
        if self._client is not None:
            return await self._analyze_with_client(self._client, source_text, payload)

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            return await self._analyze_with_client(client, source_text, payload)

    def _request_body(self, source_text: str) -> dict[str, Any]:
        return {
            "model": self._model,
            "enable_thinking": False,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Batch-specific user instructions:\n{source_text}",
                },
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "clipatlas_project_rule_candidates",
                    "strict": True,
                    "schema": _RuleAnalysisPayload.model_json_schema(),
                },
            },
        }

    async def _analyze_with_client(
        self,
        client: httpx.AsyncClient,
        source_text: str,
        payload: dict[str, Any],
    ) -> RuleAnalysisResult:
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
            raise ProviderRequestError("Rule analyzer upstream request failed") from exc

        if response.status_code in {401, 403}:
            raise ProviderAuthenticationError(
                f"Rule analyzer upstream returned HTTP {response.status_code}"
            )
        if response.status_code == 429:
            raise ProviderRateLimitError("Rule analyzer upstream returned HTTP 429")
        if response.is_error:
            raise ProviderRequestError(
                f"Rule analyzer upstream returned HTTP {response.status_code}"
            )

        try:
            body = cast(object, response.json())
            content = self._content_from_response(body)
            decoded = cast(object, json.loads(content))
            structured = _RuleAnalysisPayload.model_validate(decoded)
        except (ValueError, TypeError, json.JSONDecodeError, ValidationError) as exc:
            raise ProviderRequestError(
                "Rule analyzer returned invalid structured output"
            ) from exc

        return RuleAnalysisResult(
            source_text=source_text,
            rules=structured.rules,
        )

    @staticmethod
    def _content_from_response(payload: object) -> str:
        if not isinstance(payload, dict):
            raise ProviderRequestError("Rule analyzer returned invalid structured output")
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderRequestError("Rule analyzer returned invalid structured output")
        first = choices[0]
        if not isinstance(first, dict):
            raise ProviderRequestError("Rule analyzer returned invalid structured output")
        message = first.get("message")
        if not isinstance(message, dict):
            raise ProviderRequestError("Rule analyzer returned invalid structured output")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ProviderRequestError("Rule analyzer returned invalid structured output")
        return content

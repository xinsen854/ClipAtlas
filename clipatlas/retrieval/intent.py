import json
import logging
from typing import Any, Protocol, cast

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from clipatlas.providers.errors import (
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderRequestError,
)
from clipatlas.retrieval.storyboard import (
    STORYBOARD_PROMPT,
    Storyboard,
    apply_storyboard,
    parse_storyboard,
)
from clipatlas.roughcut.models import ScriptBeat

_DEFAULT_MODEL = "qwen3.8-flash"
logger = logging.getLogger(__name__)


class RetrievalIntent(BaseModel):
    source_text: str
    meaning: list[str] = Field(default_factory=list)
    visual_queries: list[str] = Field(default_factory=list, max_length=4)
    entities: list[str] = Field(default_factory=list)


class RetrievalIntentBuilder(Protocol):
    async def build(
        self,
        source_text: str,
        context: dict[str, object] | None = None,
    ) -> RetrievalIntent: ...


class _RetrievalIntentPayload(BaseModel):
    # AI 结构化输出偶会附带未要求的附加字段，忽略多余字段而不是让整条意图解析失败。
    model_config = ConfigDict(extra="ignore")

    meaning: list[str] = Field(default_factory=list)
    visual_queries: list[str] = Field(default_factory=list, max_length=4)
    entities: list[str] = Field(default_factory=list)


_SYSTEM_PROMPT = (
    "You convert narration or script beats into retrieval intent for video editing. "
    "Preserve stated facts and do not invent concrete facts. Identify what the audience "
    "should understand, then translate abstract meaning into camera-observable events, "
    "states, environments, interactions, demonstrations, or public evidence. Do not require "
    "visible text to repeat the narration wording. Preserve named entities when they materially "
    "narrow retrieval. Return at most four complementary, high-coverage visual queries."
)


class QwenRetrievalIntentBuilder:
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

    async def build(
        self,
        source_text: str,
        context: dict[str, object] | None = None,
    ) -> RetrievalIntent:
        if not source_text.strip():
            return RetrievalIntent(source_text=source_text)

        payload = self._request_body(source_text, context)
        if self._client is not None:
            return await self._build_with_client(self._client, source_text, payload)

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            return await self._build_with_client(client, source_text, payload)

    async def prepare_beats(
        self, beats: list[ScriptBeat], context: dict[str, object] | None = None,
    ) -> list[ScriptBeat]:
        planned: list[ScriptBeat] = []
        # Bound request/response size for long scripts; normal short narrations use one call.
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as owned_client:
            client = self._client or owned_client
            for offset in range(0, len(beats), 40):
                batch = beats[offset:offset + 40]
                payload: dict[str, Any] = {
                    "model": self._model, "enable_thinking": False,
                    "messages": [
                        {"role": "system", "content": STORYBOARD_PROMPT},
                        {"role": "user", "content": json.dumps({
                            "units": [{"sequence": index, "text": beat.text,
                                       "duration_ms": beat.target_duration_ms}
                                      for index, beat in enumerate(batch)],
                            "context": context or {},
                        }, ensure_ascii=False)},
                    ],
                    "response_format": {"type": "json_schema", "json_schema": {
                        "name": "clipatlas_storyboard", "strict": True,
                        "schema": Storyboard.model_json_schema(),
                    }},
                }
                for attempt in range(2):
                    content = await self._post_content(client, payload)
                    try:
                        group = apply_storyboard(batch, parse_storyboard(content))
                        base_sequence = len(planned)
                        planned.extend(beat.model_copy(update={"sequence": base_sequence + i})
                                       for i, beat in enumerate(group))
                        break
                    except (ValueError, ProviderRequestError) as exc:
                        logger.warning("storyboard invalid attempt=%s detail=%s content=%s", attempt + 1,
                                       str(exc).replace(self._api_key, "[redacted]")[:1000],
                                       content.replace(self._api_key, "[redacted]")[:3000])
                        if attempt:
                            raise ProviderRequestError("全文选材规划格式或覆盖范围无效，请重试") from exc
                        payload["response_format"] = {"type": "json_object"}
                        payload["messages"].append({"role": "user", "content":
                            "Return a valid object with shots, no fences. Every input sequence must "
                            "be covered once in order. Merge windows only up to 16 seconds. "
                            + str(exc)[:500]})
        return planned

    def _request_body(
        self,
        source_text: str,
        context: dict[str, object] | None,
    ) -> dict[str, Any]:
        user_content = f"Source text:\n{source_text}"
        system_prompt = _SYSTEM_PROMPT
        if context and context.get("rough_cut"):
            user_content += (
                "\nThis is ONE timed narration beat, not the whole article. Return one or two "
                "complementary concise Chinese visual queries for footage that directly illustrates "
                "THIS beat. For performance, terrain, or physical features, search actual driving, "
                "demonstrations or close-ups; do not turn a quoted experience into a talking-head "
                "query just because a speaker or broadcaster is named. For the event/interview itself, "
                "search that event. Do not require the mentioned city or named speaker to appear in "
                "generic driving/feature B-roll. Context rules are conditional guidance, not a reason "
                "to replace this beat's subject. Use narration_context ONLY to resolve the subject, "
                "vehicle type, pronouns and named entities; never replace this beat with the full story. "
                "Never invent a different vehicle category or an actual test event from numerical claims. "
                "For component strength/engineering claims, use visible component structure, clear "
                "technical diagrams/animations, or relevant ordinary use; do not demand footage of "
                "the exact stated load/pressure test unless the narration says such a test was filmed. "
                "Do not combine unrelated physical features in one query."
                " Prefer a continuous observable action or stable view that can be watched for "
                "several seconds. Do not turn every word or punctuation mark into another shot. "
                "Preserve the current content's meaning; do not force a fixed shot count or add "
                "unrelated footage solely for visual variety."
            )
        if context:
            if context.get("broaden_search"):
                user_content = f"Source text:\n{source_text}"
                system_prompt = (
                    "Extract two short concrete object/action keywords literally present in Source text "
                    "for a second-pass footage search. Use Chinese keywords of 2-4 characters when "
                    "the text is Chinese. Do not add brands, shot types, camera-distance words, "
                    "adjectives, internal structures or tests that are not in the source. Keep the "
                    "current subject. Return exactly one JSON object with visual_queries (the keywords), "
                    "meaning (empty array), entities (empty array). Example: a paragraph about seat "
                    "comfort and lumbar support yields visual_queries=[\"座椅\",\"腰托\"]."
                )
            context = {key: value for key, value in context.items()
                       if key in {"base_retrieval_query", "semantic_hints", "narration_context"}}
            user_content += (
                "\nOptional retrieval context:\n"
                + json.dumps(context, ensure_ascii=False, default=str)
            )

        return {
            "model": self._model,
            "enable_thinking": False,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "clipatlas_retrieval_intent",
                    "strict": True,
                    "schema": _RetrievalIntentPayload.model_json_schema(),
                },
            },
        }

    async def _build_with_client(
        self,
        client: httpx.AsyncClient,
        source_text: str,
        payload: dict[str, Any],
    ) -> RetrievalIntent:
        content = await self._post_content(client, payload)
        try:
            decoded = cast(object, json.loads(content))
            if not isinstance(decoded, dict):
                raise ValueError("structured response must be an object")
            structured = _RetrievalIntentPayload.model_validate({
                key: decoded[key] for key in ("meaning", "visual_queries", "entities") if key in decoded
            })
        except (ValueError, TypeError, ValidationError) as exc:
            raise ProviderRequestError("Retrieval intent returned invalid structured output") from exc
        return RetrievalIntent(source_text=source_text, **structured.model_dump())

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
            raise ProviderRequestError("Retrieval intent upstream request failed") from exc

        if response.status_code in {401, 403}:
            raise ProviderAuthenticationError(
                f"Retrieval intent upstream returned HTTP {response.status_code}"
            )
        if response.status_code == 429:
            raise ProviderRateLimitError("Retrieval intent upstream returned HTTP 429")
        if response.is_error:
            raise ProviderRequestError(
                f"Retrieval intent upstream returned HTTP {response.status_code}"
            )

        try:
            return self._content_from_response(response.json())
        except ValueError as exc:
            raise ProviderRequestError("Retrieval intent returned invalid JSON") from exc

    @staticmethod
    def _content_from_response(payload: object) -> str:
        if not isinstance(payload, dict):
            raise ProviderRequestError(
                "Retrieval intent returned invalid structured output"
            )
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderRequestError(
                "Retrieval intent returned invalid structured output"
            )
        first = choices[0]
        if not isinstance(first, dict):
            raise ProviderRequestError(
                "Retrieval intent returned invalid structured output"
            )
        message = first.get("message")
        if not isinstance(message, dict):
            raise ProviderRequestError(
                "Retrieval intent returned invalid structured output"
            )
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ProviderRequestError(
                "Retrieval intent returned invalid structured output"
            )
        return content

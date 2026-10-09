"""Shared OpenAI-compatible multimodal provider for ClipAtlas video indexing.

Covers the low-cost/zero-cost routes validated for this project:

- Zhipu GLM-4.1V-Thinking-Flash (free tier, native video input)
- DeepSeek V4-Flash-Vision-Exp (pay-per-use, image-frame input only)

Both expose an OpenAI-compatible ``/chat/completions`` endpoint, so one
transport handles retries, structured-output repair and error mapping.
"""

import base64
import json
import logging
import re
from pathlib import Path
from typing import Any, cast
from urllib.parse import unquote, urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from clipatlas.domain.models import AnnotationOrigin, ObjectiveFact, SemanticAnnotation
from clipatlas.providers.contracts import (
    AnalyzeSegmentRequest,
    AnalyzeSegmentResult,
    ProviderCapabilities,
)
from clipatlas.providers.errors import (
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderStructuredOutputError,
)
from clipatlas.providers.evidence_contract import (
    INGEST_CONTRACT_PROMPT,
    SemanticLanguageError,
    frame_context,
    semantic_language_issues,
    validate_facts,
    validate_semantic_language,
)

_JSON_FIELDS = (
    "Return ONE JSON object with these fields, not an array or a JSON schema: "
    "description (nonempty string); characters, actions, scene, emotions, objects, ocr "
    "(arrays of strings, use [] when nothing is observed); shot_type, camera_motion "
    "(string or null); confidence, query_relevance_score (number from 0 to 1 or null); "
    "query_relevance_reason (string or null). Write semantic descriptions and labels in "
    "Simplified Chinese; preserve brand/model/acronym spellings and OCR exactly as visible. "
    "Use only actual evidence from the supplied "
    "frames or video. Do not add other keys."
) + INGEST_CONTRACT_PROMPT
_FRAME_MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
logger = logging.getLogger(__name__)


class SegmentSemantics(BaseModel):
    """Structured payload shared by OpenAI-compatible providers."""

    # AI 结构化输出偶会附带未要求的附加字段，忽略多余字段而不是让整段批注失败。
    model_config = ConfigDict(extra="ignore")

    description: str
    characters: list[str]
    actions: list[str]
    scene: list[str]
    emotions: list[str]
    objects: list[str]
    ocr: list[str]
    shot_type: str | None
    camera_motion: str | None
    confidence: float | None = Field(ge=0.0, le=1.0)
    query_relevance_score: float | None = Field(default=None, ge=0.0, le=1.0)
    query_relevance_reason: str | None = None
    facts: list[ObjectiveFact] = Field(default_factory=list)


class OpenAICompatVideoProvider:
    """Base class; subclasses only override name/model/native-video support."""

    name = "openai-compat"
    _default_model = ""
    _native_video_input = False

    def __init__(
        self,
        api_key: str,
        base_url: str,
        local_frame_root: Path,
        *,
        default_model: str | None = None,
        timeout_seconds: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("api_key must not be empty")
        if not base_url.strip():
            raise ValueError("base_url must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._local_frame_root = local_frame_root.expanduser().resolve(strict=False)
        self._default_model = default_model or self._default_model
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            native_video_input=self._native_video_input,
            image_input=True,
            ocr=True,
            semantic_segmentation=True,
            structured_output=True,
        )

    def _local_frame_to_data_uri(self, uri: str) -> str:
        parsed = urlparse(uri)
        path_text = unquote(parsed.path)
        if (
            len(path_text) >= 3
            and path_text[0] == "/"
            and path_text[1].isalpha()
            and path_text[2] == ":"
        ):
            path_text = path_text[1:]
        path = Path(path_text)
        resolved = path.expanduser().resolve(strict=False)
        if not resolved.is_relative_to(self._local_frame_root):
            raise ProviderRequestError("local frame is outside configured local frame root")
        if not resolved.is_file():
            raise ProviderRequestError("local frame does not exist or is not a regular file")
        mime_type = _FRAME_MIME_TYPES.get(resolved.suffix.lower())
        if mime_type is None:
            raise ProviderRequestError("local frame has an unsupported image extension")
        encoded = base64.b64encode(resolved.read_bytes()).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    def _frame_input_uri(self, uri: str) -> str:
        parsed = urlparse(uri)
        if parsed.scheme in {"http", "https", "data"}:
            return uri
        if parsed.scheme == "file":
            return self._local_frame_to_data_uri(uri)
        raise ProviderRequestError("frame URI must use http, https, data, or file scheme")

    def _multimodal_content(self, request: AnalyzeSegmentRequest) -> list[dict[str, Any]]:
        content: list[dict[str, Any]] = []
        if request.frame_uris:
            content.extend(
                {
                    "type": "image_url",
                    "image_url": {"url": self._frame_input_uri(uri)},
                }
                for uri in request.frame_uris
            )
        elif self._native_video_input and request.context.get("analysis_scope") == "whole_video":
            parsed = urlparse(request.source_uri)
            if parsed.scheme not in {"http", "https", "data"}:
                raise ProviderRequestError(
                    "whole-video native input requires an http, https, or data source URI"
                )
            content.append(
                {
                    "type": "video_url",
                    "video_url": {"url": request.source_uri},
                }
            )
        else:
            raise ProviderRequestError(
                "at least one representative frame is required"
                if not self._native_video_input
                else "at least one representative frame or a whole-video source URI is required"
            )

        prompt = (
            "Analyze this ClipAtlas segment from "
            f"{request.start_ms}ms to {request.end_ms}ms. "
            "Describe only visually supported evidence. Be concrete about people, actions, "
            "location, visible objects, readable OCR, shot type, camera motion, and visible "
            "emotional cues. Do not invent identity, dialogue, story facts, or edit boundaries. "
            "The result will later be embedded and matched against narration/script beats for "
            "automatic rough-cut footage selection. "
            + _JSON_FIELDS
        )
        content.append({"type": "text", "text": prompt + "\n" + frame_context(request)})
        return content

    def _request_body(self, request: AnalyzeSegmentRequest, model: str) -> dict[str, Any]:
        return {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are ClipAtlas visual indexing. Return faithful, retrieval-friendly "
                        "segment semantics. Prefer literal visual evidence over narrative guesses. "
                        + _JSON_FIELDS
                    ),
                },
                {
                    "role": "user",
                    "content": self._multimodal_content(request),
                },
            ],
            # json_object is the most portable structured-output mode across
            # Zhipu/DeepSeek OpenAI-compatible endpoints; the prompt enforces JSON.
            "response_format": {"type": "json_object"},
        }

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        try:
            payload = cast(object, response.json())
        except ValueError:
            text = response.text.strip()
            return text or f"HTTP {response.status_code}"
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                message = error.get("message")
                if isinstance(message, str) and message.strip():
                    return message.strip()
            message = payload.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        return f"HTTP {response.status_code}"

    @staticmethod
    def _content_from_response(payload: object) -> str:
        if not isinstance(payload, dict):
            raise ProviderStructuredOutputError("provider returned an invalid response payload")
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderStructuredOutputError("provider response is missing choices")
        first = choices[0]
        if not isinstance(first, dict):
            raise ProviderStructuredOutputError("provider response contains an invalid choice")
        message = first.get("message")
        if not isinstance(message, dict):
            raise ProviderStructuredOutputError("provider response is missing message")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ProviderStructuredOutputError("provider response is missing structured content")
        return content

    @staticmethod
    def _parse_semantics(content: str) -> SegmentSemantics:
        text = content.strip()
        fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
        if fenced is not None:
            text = fenced.group(1)
        payload = json.loads(text)
        if isinstance(payload, list):
            if len(payload) != 1 or not isinstance(payload[0], dict):
                raise ValueError(f"expected one semantic object, got array[{len(payload)}]")
            payload = payload[0]
        if isinstance(payload, dict) and payload.get("additionalProperties") is False:
            payload = {key: value for key, value in payload.items() if key != "additionalProperties"}
        semantic = SegmentSemantics.model_validate(payload)
        if not semantic.description.strip():
            raise ValueError("description is empty")
        return semantic

    @staticmethod
    def _validation_detail(error: Exception) -> str:
        if isinstance(error, ValidationError):
            return "; ".join(
                f"{'.'.join(map(str, item['loc'])) or 'root'}: {item['msg']}"
                for item in error.errors(include_input=False, include_url=False)[:8]
            )
        if isinstance(error, json.JSONDecodeError):
            return f"invalid JSON at line {error.lineno}, column {error.colno}: {error.msg}"
        return str(error)[:1000]

    async def analyze_segment(self, request: AnalyzeSegmentRequest) -> AnalyzeSegmentResult:
        model = self._default_model
        body = self._request_body(request, model)
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        upstream: object = None
        semantic: SegmentSemantics
        language_issues: list[str] = []
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=self._timeout_seconds,
            ) as client:
                for attempt in range(2):
                    response = await client.post(
                        f"{self._base_url}/chat/completions",
                        headers=headers,
                        json=body,
                    )

                    if response.status_code in {401, 403}:
                        raise ProviderAuthenticationError(self._error_detail(response))
                    if response.status_code == 429:
                        raise ProviderRateLimitError(self._error_detail(response))
                    if response.is_error:
                        raise ProviderRequestError(self._error_detail(response))

                    content = ""
                    upstream = None
                    try:
                        upstream = cast(object, response.json())
                        content = self._content_from_response(upstream)
                        semantic = self._parse_semantics(content)
                        facts = validate_facts(semantic.facts, request)
                        language_fields = {
                            "description": semantic.description,
                            "characters": semantic.characters,
                            "actions": semantic.actions,
                            "scene": semantic.scene,
                            "emotions": semantic.emotions,
                            "objects": semantic.objects,
                            "facts": semantic.facts,
                        }
                        language_issues = semantic_language_issues(**language_fields)
                        if language_issues and attempt == 0:
                            validate_semantic_language(**language_fields)
                        if attempt:
                            logger.info(
                                "structured output recovered provider=%s model=%s video=%s segment=%s",
                                self.name, model, request.video_id, request.segment_id,
                            )
                        break
                    except (ValueError, ProviderStructuredOutputError) as exc:
                        detail = self._validation_detail(exc).replace(self._api_key, "[redacted]")
                        response_id = response.headers.get("x-request-id") or (
                            str(upstream.get("id", "unknown"))
                            if isinstance(upstream, dict)
                            else "unknown"
                        )
                        logger.warning(
                            "invalid structured output provider=%s model=%s video=%s segment=%s "
                            "range=%s-%s attempt=%s request_id=%s detail=%r",
                            self.name, model, request.video_id, request.segment_id,
                            request.start_ms, request.end_ms, attempt + 1, response_id, detail,
                        )
                        if attempt == 1:
                            raise ProviderStructuredOutputError(
                                f"{self.name} returned invalid structured semantics after one "
                                f"repair retry; {detail}; model={model}; request_id={response_id}; "
                                f"video={request.video_id}, range={request.start_ms}-{request.end_ms}ms"
                            ) from exc
                        repair = (
                            "Keep the same JSON structure and evidence. Translate only description, "
                            "characters, actions, scene, emotions, objects, and semantic fact values "
                            "into Simplified Chinese. Preserve OCR, brand/model names, acronyms, frame "
                            "IDs, timestamps, entity IDs and proposition predicates exactly. "
                            if isinstance(exc, SemanticLanguageError)
                            else f"The previous response was invalid ({detail}). Correct its format. "
                        )
                        body = {
                            **body,
                            "messages": [
                                *body["messages"],
                                {"role": "assistant", "content": content},
                                {
                                    "role": "user",
                                    "content": (
                                        repair + "Output JSON only, without Markdown fences. "
                                        + _JSON_FIELDS
                                    ),
                                },
                            ],
                        }
        except httpx.HTTPError as exc:
            raise ProviderRequestError(f"{self.name} request failed: {exc}") from exc

        annotation = SemanticAnnotation(
            segment_id=request.segment_id,
            origin=AnnotationOrigin.AI,
            provider=self.name,
            model=model,
            description=semantic.description,
            characters=semantic.characters,
            actions=semantic.actions,
            scene=semantic.scene,
            emotions=semantic.emotions,
            objects=semantic.objects,
            ocr=semantic.ocr,
            shot_type=semantic.shot_type,
            camera_motion=semantic.camera_motion,
            facts=facts,
            confidence=semantic.confidence,
            raw_payload={
                "upstream": upstream,
                "semantic_language": "english_fallback" if language_issues else "zh-CN",
                "semantic_language_issues": language_issues,
            },
        )
        return AnalyzeSegmentResult(
            provider=self.name,
            model=model,
            annotation=annotation,
            query_relevance_score=semantic.query_relevance_score,
            query_relevance_reason=semantic.query_relevance_reason,
        )

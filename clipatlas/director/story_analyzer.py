from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import ValidationError

from clipatlas.director.story_models import (
    StoryAnalysisResult,
    StoryEvidencePacket,
    StorySkill,
)
from clipatlas.providers.errors import (
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderStructuredOutputError,
)

DEFAULT_STORY_MODEL = "qwen3.8-flash"
STORY_PROMPT_VERSION = "auto-director-story-v1"


def _strict_schema() -> dict[str, Any]:
    schema = StoryAnalysisResult.model_json_schema()

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


class StoryAnalyzer:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str = DEFAULT_STORY_MODEL,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 180.0,
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

    async def analyze(
        self,
        skill: StorySkill,
        packet: StoryEvidencePacket,
    ) -> StoryAnalysisResult:
        evidence_payload = [item.model_dump(mode="json") for item in packet.items]
        payload = {
            "model": self._model,
            "enable_thinking": False,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是 ClipAtlas 自动编导。你的任务不是写小说，而是把已经存在的真实素材重新组织成更有效的故事。"
                        "Story Skill 只规定怎么讲，不代表素材中真的发生了某件事。"
                        "所有故事节点都必须引用输入中真实存在的 evidence_id；禁止编造 evidence_id、人物、事件、死亡、事故、反转或因果。"
                        "如果 Skill 要求的钩子或反转没有证据，必须在 warnings 里说明并采用证据支持的最强结构。"
                        "允许把结果放在开头做钩子，也允许非线性重排，但 summary 必须忠于素材。"
                        "节点 evidence_ids 至少一个。输出简体中文结构化 JSON，不要输出 JSON 之外的文字。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Story Skill 名称：{skill.name}\n\n"
                        f"Story Skill 内容：\n{skill.content}\n\n"
                        f"项目 ID：{packet.project_id}\n"
                        f"视频数量：{packet.video_count}\n"
                        "以下是按项目素材整理的真实证据。只能引用这些 evidence_id：\n"
                        + json.dumps(evidence_payload, ensure_ascii=False)
                    ),
                },
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "clipatlas_auto_director_story_outline",
                    "strict": True,
                    "schema": _strict_schema(),
                },
            },
        }

        if self._client is not None:
            content = await self._post_content(self._client, payload)
        else:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                content = await self._post_content(client, payload)

        try:
            decoded = json.loads(content)
            return StoryAnalysisResult.model_validate(decoded)
        except (ValueError, TypeError, ValidationError) as exc:
            raise ProviderStructuredOutputError(
                "Auto Director returned invalid story outline"
            ) from exc

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
            raise ProviderRequestError("Auto Director upstream request failed") from exc

        if response.status_code in {401, 403}:
            raise ProviderAuthenticationError(
                f"Auto Director upstream returned HTTP {response.status_code}"
            )
        if response.status_code == 429:
            raise ProviderRateLimitError("Auto Director upstream returned HTTP 429")
        if response.is_error:
            raise ProviderRequestError(
                f"Auto Director upstream returned HTTP {response.status_code}"
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderRequestError("Auto Director returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise ProviderStructuredOutputError("Auto Director response is not an object")
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderStructuredOutputError("Auto Director response has no choices")
        first = choices[0]
        if not isinstance(first, dict):
            raise ProviderStructuredOutputError("Auto Director response choice is invalid")
        message = first.get("message")
        if not isinstance(message, dict):
            raise ProviderStructuredOutputError("Auto Director response message is invalid")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ProviderStructuredOutputError("Auto Director response content is empty")
        return content

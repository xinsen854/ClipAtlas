import base64
import json
from pathlib import Path
from typing import Any

import httpx

from clipatlas.asr.models import ASRSentence, ASRWord
from clipatlas.providers.errors import (
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderRequestError,
)
from clipatlas.providers.requests import RequestPolicy, check_retryable_response

_MAX_ENCODED_AUDIO_BYTES = 10_000_000
_DATA_URI_PREFIX = "data:audio/wav;base64,"
_ASR_PATH = "services/aigc/multimodal-generation/generation"


class QwenAudioASRProvider:
    name = "bailian-asr"
    model = "qwen-audio-3.0-asr-flash"

    def __init__(
        self,
        *,
        api_key: str,
        api_root: str,
        client: httpx.AsyncClient | None = None,
        request_policy: RequestPolicy | None = None,
        timeout_seconds: float = 300.0,
    ) -> None:
        if not api_key.strip():
            raise ValueError("api_key is required")
        if not api_root.strip():
            raise ValueError("api_root is required")
        self._api_key = api_key.strip()
        self._api_root = api_root.strip().rstrip("/")
        self._client = client
        self._request_policy = request_policy
        self._timeout_seconds = timeout_seconds

    async def transcribe(self, audio_path: Path) -> list[ASRSentence]:
        audio_path = audio_path.resolve()
        if not audio_path.is_file():
            raise FileNotFoundError(audio_path)

        raw_size = audio_path.stat().st_size
        encoded_size = 4 * ((raw_size + 2) // 3) + len(_DATA_URI_PREFIX)
        if encoded_size > _MAX_ENCODED_AUDIO_BYTES:
            raise ProviderRequestError("ASR Base64 input exceeds the 10 MB API limit")

        encoded = base64.b64encode(audio_path.read_bytes()).decode("ascii")
        payload = {
            "model": self.model,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_audio",
                                "input_audio": {
                                    "data": f"{_DATA_URI_PREFIX}{encoded}",
                                },
                            }
                        ],
                    }
                ]
            },
            "parameters": {"format": "wav", "sample_rate": 16000},
        }

        async def call(client: httpx.AsyncClient) -> list[ASRSentence]:
            if self._request_policy is None:
                return await self._transcribe_with_client(client, payload)
            return await self._request_policy.run(lambda: self._transcribe_with_client(client, payload))

        if self._client is not None:
            return await call(self._client)
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            return await call(client)

    async def _transcribe_with_client(
        self,
        client: httpx.AsyncClient,
        payload: dict[str, Any],
    ) -> list[ASRSentence]:
        url = f"{self._api_root}/{_ASR_PATH}"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "X-DashScope-SSE": "enable",
        }
        try:
            async with client.stream(
                "POST",
                url,
                headers=headers,
                json=payload,
                timeout=self._timeout_seconds,
            ) as response:
                if self._request_policy is not None:
                    check_retryable_response(response)
                self._raise_for_status(response.status_code)
                content_type = response.headers.get("content-type", "").lower()
                if "text/event-stream" in content_type:
                    return await self._parse_sse_response(response)
                body = await response.aread()
                text = body.decode("utf-8", errors="ignore")
                # 部分网关不按 SSE 声明 content-type，但实际返回 data: 事件流 → 先按 SSE 行解析
                if "data:" in text:
                    try:
                        return self._parse_sse_text(text)
                    except ProviderRequestError:
                        pass
                return self._parse_event(text)
        except (
            ProviderAuthenticationError,
            ProviderRateLimitError,
            ProviderRequestError,
        ):
            raise
        except httpx.RequestError as exc:
            raise ProviderRequestError("ASR upstream request failed") from exc

    async def _parse_sse_response(self, response: httpx.Response) -> list[ASRSentence]:
        sentences: list[ASRSentence] = []
        async for line in response.aiter_lines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            sentences.extend(self._parse_event(data))
        return sentences

    @classmethod
    def _parse_sse_text(cls, text: str) -> list[ASRSentence]:
        """同步解析 SSE 文本（用于 content-type 未声明 SSE 的响应体）。"""
        sentences: list[ASRSentence] = []
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            sentences.extend(cls._parse_event(data))
        return sentences

    @staticmethod
    def _raise_for_status(status_code: int) -> None:
        if 200 <= status_code < 300:
            return
        if status_code in {401, 403}:
            raise ProviderAuthenticationError(f"ASR upstream returned HTTP {status_code}")
        if status_code == 429:
            raise ProviderRateLimitError("ASR upstream returned HTTP 429")
        raise ProviderRequestError(f"ASR upstream returned HTTP {status_code}")

    @classmethod
    def _parse_event(cls, data: str) -> list[ASRSentence]:
        try:
            payload: Any = json.loads(data)
        except json.JSONDecodeError as exc:
            raise ProviderRequestError(
                f"ASR returned an invalid response payload: {data[:200]}"
            ) from exc
        if not isinstance(payload, dict):
            raise ProviderRequestError(
                f"ASR returned an invalid response payload: {data[:200]}"
            )

        # 服务端显式错误（key 无效、额度不足等）→ 带信息报错
        code = payload.get("code")
        message = payload.get("message")
        if code or message:
            combined = f"{code or ''} {message or ''}".strip()
            # 无语音（纯音乐 / 静音 / 无口播）：服务端显式返回无识别词 → 空结果，不算错误
            if "NO_WORDS" in combined.upper() or "HAVE_NO_WORDS" in combined.upper():
                return []
            raise ProviderRequestError(f"ASR upstream error: {combined}")

        output = payload.get("output")
        sentence = output.get("sentence") if isinstance(output, dict) else None
        # 无语音（纯音乐 / 静音 / 无口播）：没有 sentence → 空结果，不算错误
        if sentence is None:
            return []
        if not isinstance(sentence, dict):
            raise ProviderRequestError("ASR returned an invalid sentence payload")
        if not sentence.get("sentence_end"):
            return []

        try:
            start_ms = int(sentence["begin_time"])
            end_ms = int(sentence["end_time"])
            text = str(sentence["text"])
            raw_words = sentence.get("words", [])
            if not isinstance(raw_words, list):
                raise TypeError("words must be a list")
            words = [cls._parse_word(word) for word in raw_words]
            return [
                ASRSentence(
                    start_ms=start_ms,
                    end_ms=end_ms,
                    text=text,
                    words=words,
                )
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderRequestError("ASR returned invalid timestamp data") from exc

    @staticmethod
    def _parse_word(raw: Any) -> ASRWord:
        if not isinstance(raw, dict):
            raise TypeError("word must be an object")
        return ASRWord(
            start_ms=int(raw["begin_time"]),
            end_ms=int(raw["end_time"]),
            text=str(raw["text"]),
            punctuation=str(raw.get("punctuation", "")),
        )

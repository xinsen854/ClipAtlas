import base64
from pathlib import Path
from typing import Any

import httpx

from clipatlas.providers.errors import (
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderRequestError,
)
from clipatlas.providers.requests import RequestPolicy, check_retryable_response

_MAX_DATA_URI_BYTES = 10_000_000
_DATA_URI_PREFIX = "data:image/jpeg;base64,"
_OCR_PROMPT = (
    "You are an OCR engine, not an image-captioning model. Extract only text that is "
    "visibly printed, overlaid, subtitled, or written in the image. Preserve the visible "
    "text's original language and spelling exactly. Do not translate, summarize, infer, "
    "explain, or describe people, objects, actions, scenes, atmosphere, or story. If the "
    "image contains no visible text, return an empty string. Output raw OCR text only, "
    "without Markdown, JSON, labels, or commentary."
)


class QwenOCRProvider:
    name = "bailian-ocr"
    model = "qwen3.5-ocr"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        client: httpx.AsyncClient | None = None,
        request_policy: RequestPolicy | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        if not api_key.strip():
            raise ValueError("api_key is required")
        if not base_url.strip():
            raise ValueError("base_url is required")
        self._api_key = api_key.strip()
        self._base_url = base_url.strip().rstrip("/")
        self._client = client
        self._request_policy = request_policy
        self._timeout_seconds = timeout_seconds

    async def recognize(self, image_path: Path) -> str:
        image_path = image_path.resolve()
        if not image_path.is_file():
            raise FileNotFoundError(image_path)

        raw_size = image_path.stat().st_size
        encoded_size = 4 * ((raw_size + 2) // 3) + len(_DATA_URI_PREFIX)
        if encoded_size > _MAX_DATA_URI_BYTES:
            raise ProviderRequestError("OCR Base64 input exceeds the 10 MB API limit")

        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"{_DATA_URI_PREFIX}{encoded}",
                            },
                            "min_pixels": 3072,
                            "max_pixels": 8388608,
                        },
                        {
                            "type": "text",
                            "text": _OCR_PROMPT,
                        },
                    ],
                }
            ],
        }

        async def call(client: httpx.AsyncClient) -> str:
            if self._request_policy is None:
                return await self._recognize_with_client(client, payload)
            return await self._request_policy.run(lambda: self._recognize_with_client(client, payload))

        if self._client is not None:
            return await call(self._client)
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            return await call(client)

    async def _recognize_with_client(
        self,
        client: httpx.AsyncClient,
        payload: dict[str, Any],
    ) -> str:
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
            if self._request_policy is not None:
                check_retryable_response(response)
            self._raise_for_status(response.status_code)
            try:
                body = response.json()
                content = body["choices"][0]["message"]["content"]
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                raise ProviderRequestError("OCR returned an invalid response payload") from exc
            if not isinstance(content, str):
                raise ProviderRequestError("OCR returned an invalid response payload")
            return content
        except (
            ProviderAuthenticationError,
            ProviderRateLimitError,
            ProviderRequestError,
        ):
            raise
        except httpx.RequestError as exc:
            raise ProviderRequestError("OCR upstream request failed") from exc

    @staticmethod
    def _raise_for_status(status_code: int) -> None:
        if 200 <= status_code < 300:
            return
        if status_code in {401, 403}:
            raise ProviderAuthenticationError(f"OCR upstream returned HTTP {status_code}")
        if status_code == 429:
            raise ProviderRateLimitError("OCR upstream returned HTTP 429")
        raise ProviderRequestError(f"OCR upstream returned HTTP {status_code}")

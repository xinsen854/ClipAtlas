import math
from typing import Any, cast

import httpx

from clipatlas.embeddings.contracts import EmbeddingVector
from clipatlas.providers.errors import (
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderRequestError,
)


class QwenTextEmbeddingProvider:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str = "text-embedding-v4",
        dimensions: int = 1024,
        timeout_seconds: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        api_key = api_key.strip()
        base_url = base_url.strip().rstrip("/")
        model = model.strip()
        if not api_key:
            raise ValueError("api_key must not be empty")
        if not base_url:
            raise ValueError("base_url must not be empty")
        if not model:
            raise ValueError("model must not be empty")
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

        self._api_key = api_key
        self._base_url = base_url
        self._model = model
        self._dimensions = dimensions
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    @property
    def name(self) -> str:
        return "qwen-embedding"

    @property
    def model(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text.strip() or f"HTTP {response.status_code}"
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

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        detail = self._error_detail(response)
        if response.status_code in {401, 403}:
            raise ProviderAuthenticationError(detail)
        if response.status_code == 429:
            raise ProviderRateLimitError(detail)
        raise ProviderRequestError(detail)

    def _parse_vector(self, value: object) -> EmbeddingVector:
        if not isinstance(value, list):
            raise ProviderRequestError("embedding vector must be a list")
        if len(value) != self._dimensions:
            raise ProviderRequestError(
                f"embedding dimension mismatch: expected {self._dimensions}, got {len(value)}"
            )

        values: list[float] = []
        for item in value:
            if isinstance(item, bool) or not isinstance(item, (int, float)):
                raise ProviderRequestError("embedding values must be numeric")
            number = float(item)
            if not math.isfinite(number):
                raise ProviderRequestError("embedding values must be finite")
            values.append(number)
        return EmbeddingVector(values=values)

    def _parse_response(self, payload: object, expected_count: int) -> list[EmbeddingVector]:
        if not isinstance(payload, dict):
            raise ProviderRequestError("embedding response must be an object")
        data = payload.get("data")
        if not isinstance(data, list):
            raise ProviderRequestError("embedding response is missing data")
        if len(data) != expected_count:
            raise ProviderRequestError(
                f"embedding result count mismatch: expected {expected_count}, got {len(data)}"
            )

        ordered: dict[int, EmbeddingVector] = {}
        for item in data:
            if not isinstance(item, dict):
                raise ProviderRequestError("embedding result item must be an object")
            index = item.get("index")
            if isinstance(index, bool) or not isinstance(index, int):
                raise ProviderRequestError("embedding result index must be an integer")
            if index < 0 or index >= expected_count or index in ordered:
                raise ProviderRequestError("embedding result index is invalid")
            ordered[index] = self._parse_vector(item.get("embedding"))

        if len(ordered) != expected_count:
            raise ProviderRequestError("embedding response indexes are incomplete")
        return [ordered[index] for index in range(expected_count)]

    async def embed_documents(self, texts: list[str]) -> list[EmbeddingVector]:
        if not texts:
            return []

        payload: dict[str, Any] = {
            "model": self._model,
            "input": texts,
            "dimensions": self._dimensions,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout_seconds,
                transport=self._transport,
            ) as client:
                response = await client.post(
                    f"{self._base_url}/embeddings",
                    headers=headers,
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise ProviderRequestError(str(exc)) from exc

        self._raise_for_status(response)
        try:
            response_payload = cast(object, response.json())
        except ValueError as exc:
            raise ProviderRequestError("embedding response is not valid JSON") from exc
        return self._parse_response(response_payload, len(texts))

    async def embed_query(self, text: str) -> EmbeddingVector:
        vectors = await self.embed_documents([text])
        if len(vectors) != 1:
            raise ProviderRequestError("embedding query did not return exactly one vector")
        return vectors[0]

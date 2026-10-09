"""ClipAtlas request admission over the unchanged SentrySearch SDK core."""

import os
import threading
import time
from typing import Any, cast

from clipatlas.providers.errors import ProviderAuthenticationError, ProviderRequestError
from clipatlas.vendor.sentrysearch.qwen_cloud_embedder import (
    QwenCloudEmbedder,
    _retry,
)


class RateLimiter:
    def __init__(self, rpm: int) -> None:
        if rpm < 1:
            raise ValueError("RPM must be positive")
        self._interval = 60.0 / rpm
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            delay = self._next - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            self._next = time.monotonic() + self._interval


_LIMITERS: dict[str, RateLimiter] = {}
_LIMITERS_LOCK = threading.Lock()


class ConcurrentQwenCloudEmbedder(QwenCloudEmbedder):
    def __init__(
        self, model_name: str | None = None, *, dimensions: int = 768,
        video_fps: float | None = None,
    ) -> None:
        super().__init__(model_name, dimensions=dimensions, video_fps=video_fps)
        with _LIMITERS_LOCK:
            self._admission = _LIMITERS.setdefault(
                self._model, RateLimiter(int(os.getenv("DASHSCOPE_RPM", "180"))),
            )

    def _embed_one(
        self, contents: list[dict[str, Any]], parameters: dict[str, Any], *,
        verbose: bool, label: str, extra_kb: float | None = None,
    ) -> list[float]:
        def call() -> list[float]:
            # Admit every attempt, including retries, across index and query calls.
            self._admission.wait()
            response = self._MultiModalEmbedding.call(
                model=self._model, input=contents, api_key=self._api_key,
                parameters=parameters, timeout=120,
            )
            status = getattr(response, "status_code", None)
            if status in {401, 403}:
                raise ProviderAuthenticationError(f"DashScope upstream returned HTTP {status}")
            if isinstance(status, int) and 400 <= status < 500 and status != 429:
                # Avoid the vendor retry heuristic matching arbitrary words in a 400 response.
                raise ProviderRequestError(f"DashScope upstream returned HTTP {status}")
            return self._parse_embedding_response(response)

        return cast(list[float], _retry(call, max_retries=3, max_delay=30))

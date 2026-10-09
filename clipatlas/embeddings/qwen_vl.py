import asyncio
import importlib
import math
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, cast

from clipatlas.concurrency import drain_on_cancel
from clipatlas.embeddings.contracts import EmbeddingVector
from clipatlas.providers.errors import (
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderRequestError,
)

_DEFAULT_MODEL = "qwen3-vl-embedding"
_EFFECTIVE_DIMENSIONS = 2560


class _VendorQwenEmbedder(Protocol):
    def embed_video_chunk(self, chunk_path: str, verbose: bool = False) -> list[float]: ...

    def embed_query(self, query_text: str, verbose: bool = False) -> list[float]: ...


_EmbedderFactory = Callable[..., _VendorQwenEmbedder]


class QwenVLVideoEmbeddingProvider:
    """ClipAtlas adapter over the vendored SentrySearch Qwen embedding core."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = _DEFAULT_MODEL,
        base_http_api_url: str | None = None,
        embedder_factory: _EmbedderFactory | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_http_api_url = (
            base_http_api_url.strip().rstrip("/") if base_http_api_url else None
        )
        self._embedder = self._build_embedder(embedder_factory)

    def _build_embedder(self, embedder_factory: _EmbedderFactory | None) -> _VendorQwenEmbedder:
        had_previous_key = "DASHSCOPE_API_KEY" in os.environ
        previous_key = os.environ.get("DASHSCOPE_API_KEY")
        os.environ["DASHSCOPE_API_KEY"] = self._api_key
        try:
            if self._base_http_api_url:
                try:
                    dashscope_module = importlib.import_module("dashscope")
                except ImportError as exc:
                    raise ProviderRequestError(
                        "DashScope video embedding support is not installed; "
                        "install ClipAtlas with the video-embedding extra"
                    ) from exc
                dynamic_dashscope: Any = dashscope_module
                dynamic_dashscope.base_http_api_url = self._base_http_api_url

            factory = embedder_factory or self._load_vendor_factory()
            return factory(
                model_name=self._model,
                dimensions=_EFFECTIVE_DIMENSIONS,
            )
        except (ProviderAuthenticationError, ProviderRateLimitError, ProviderRequestError):
            raise
        except Exception as exc:
            raise self._normalize_vendor_error(exc) from exc
        finally:
            if had_previous_key:
                os.environ["DASHSCOPE_API_KEY"] = previous_key or ""
            else:
                os.environ.pop("DASHSCOPE_API_KEY", None)

    @staticmethod
    def _load_vendor_factory() -> _EmbedderFactory:
        try:
            module = importlib.import_module(
                "clipatlas.embeddings.cloud_requests"
            )
            dynamic_module: Any = module
            factory = dynamic_module.ConcurrentQwenCloudEmbedder
        except (ImportError, AttributeError) as exc:
            raise ProviderRequestError("Vendored SentrySearch Qwen embedder is unavailable") from exc
        return cast(_EmbedderFactory, factory)

    @property
    def name(self) -> str:
        return "qwen-vl-video"

    @property
    def model(self) -> str:
        return self._model

    @property
    def effective_dimensions(self) -> int:
        return _EFFECTIVE_DIMENSIONS

    async def embed_video(self, video_path: Path) -> EmbeddingVector:
        source = video_path.expanduser().resolve(strict=False)
        if not source.is_file():
            raise FileNotFoundError(f"Video chunk not found: {source}")
        try:
            raw_vector = await drain_on_cancel(asyncio.to_thread(
                self._embedder.embed_video_chunk,
                str(source),
            ))
        except (ProviderAuthenticationError, ProviderRateLimitError, ProviderRequestError):
            raise
        except Exception as exc:
            raise self._normalize_vendor_error(exc) from exc
        return self._embedding_vector(raw_vector)

    async def embed_query(self, text: str) -> EmbeddingVector:
        try:
            raw_vector = await drain_on_cancel(asyncio.to_thread(self._embedder.embed_query, text))
        except (ProviderAuthenticationError, ProviderRateLimitError, ProviderRequestError):
            raise
        except Exception as exc:
            raise self._normalize_vendor_error(exc) from exc
        return self._embedding_vector(raw_vector)

    @staticmethod
    def _normalize_vendor_error(exc: Exception) -> Exception:
        message = str(exc) or "DashScope video embedding request failed"
        lowered = message.lower()
        if "http 401" in lowered or "http 403" in lowered:
            return ProviderAuthenticationError(message)
        if (
            "http 429" in lowered
            or "rate limit" in lowered
            or "rate-limit" in lowered
            or "ratelimit" in lowered
            or "throttl" in lowered
            or "quota" in lowered
        ):
            return ProviderRateLimitError(message)
        return ProviderRequestError(message)

    @staticmethod
    def _embedding_vector(raw_vector: object) -> EmbeddingVector:
        if not isinstance(raw_vector, list):
            raise ProviderRequestError("DashScope response is missing embedding vector")
        if len(raw_vector) != _EFFECTIVE_DIMENSIONS:
            raise ProviderRequestError(
                "qwen3-vl-embedding returned "
                f"{len(raw_vector)} dimensions; expected {_EFFECTIVE_DIMENSIONS}"
            )

        values: list[float] = []
        for value in raw_vector:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ProviderRequestError("Embedding values must be numeric")
            numeric = float(value)
            if not math.isfinite(numeric):
                raise ProviderRequestError("Embedding values must be finite")
            values.append(numeric)
        return EmbeddingVector(values=values)

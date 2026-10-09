from pathlib import Path

import pytest

import clipatlas.app_state as app_state_module
from clipatlas.app_state import (
    build_library_runtime,
    build_semantic_search_service,
    build_video_chunk_search_service,
)
from clipatlas.catalog.store import CatalogStore
from clipatlas.embeddings.contracts import EmbeddingVector
from clipatlas.retrieval.indexer import SemanticIndexer
from clipatlas.retrieval.search import CoarseVideoSearchService, SemanticSearchService
from clipatlas.retrieval.video_indexer import CoarseVideoIndexer


class _FakeVideoEmbeddingProvider:
    name = "qwen-vl-video"
    model = "qwen3-vl-embedding"
    effective_dimensions = 2560

    async def embed_query(self, text: str) -> EmbeddingVector:
        return EmbeddingVector(values=[1.0] + [0.0] * 2559)

    async def embed_video(self, video_path: Path) -> EmbeddingVector:
        return EmbeddingVector(values=[1.0] + [0.0] * 2559)


def test_semantic_search_runtime_is_disabled_without_embedding_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("CLIPATLAS_EMBEDDING_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    catalog = CatalogStore(tmp_path / "clipatlas.sqlite3")

    assert build_semantic_search_service(catalog) is None


def test_semantic_search_runtime_uses_embedding_key_and_dashscope_fallback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    catalog = CatalogStore(tmp_path / "clipatlas.sqlite3")
    monkeypatch.setenv("CLIPATLAS_EMBEDDING_API_KEY", "embedding-key")
    monkeypatch.setenv("CLIPATLAS_EMBEDDING_BASE_URL", "https://example.test/compatible-mode/v1")
    monkeypatch.setenv("CLIPATLAS_EMBEDDING_MODEL", "text-embedding-v4")
    monkeypatch.setenv("CLIPATLAS_EMBEDDING_DIMENSIONS", "768")

    explicit = build_semantic_search_service(catalog)
    assert isinstance(explicit, SemanticSearchService)

    monkeypatch.delenv("CLIPATLAS_EMBEDDING_API_KEY")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dashscope-key")
    fallback = build_semantic_search_service(catalog)
    assert isinstance(fallback, SemanticSearchService)


def test_video_chunk_search_runtime_is_disabled_without_shared_embedding_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("CLIPATLAS_EMBEDDING_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    catalog = CatalogStore(tmp_path / "clipatlas.sqlite3")

    assert build_video_chunk_search_service(catalog) is None


def test_video_chunk_search_runtime_reuses_embedding_workspace_credentials(
    tmp_path: Path,
    monkeypatch,
) -> None:
    catalog = CatalogStore(tmp_path / "clipatlas.sqlite3")
    monkeypatch.setenv("CLIPATLAS_EMBEDDING_API_KEY", "workspace-key")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "stale-dashscope-key")
    monkeypatch.setenv(
        "CLIPATLAS_EMBEDDING_BASE_URL",
        "https://ws-example.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    )
    captured: list[dict[str, str]] = []

    def fake_provider(*, api_key: str, base_http_api_url: str):
        captured.append(
            {
                "api_key": api_key,
                "base_http_api_url": base_http_api_url,
            }
        )
        return _FakeVideoEmbeddingProvider()

    monkeypatch.setattr(app_state_module, "QwenVLVideoEmbeddingProvider", fake_provider)

    service = build_video_chunk_search_service(catalog)

    assert isinstance(service, CoarseVideoSearchService)
    assert captured == [
        {
            "api_key": "workspace-key",
            "base_http_api_url": "https://ws-example.cn-beijing.maas.aliyuncs.com/api/v1",
        }
    ]


def test_library_runtime_injects_default_video_indexer_when_provider_is_supplied(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CLIPATLAS_LIBRARY_DB", str(tmp_path / "library.sqlite3"))
    monkeypatch.setenv("CLIPATLAS_LIBRARY_CACHE_ROOT", str(tmp_path / "cache"))
    provider = _FakeVideoEmbeddingProvider()

    runtime = build_library_runtime(video_embedding_provider=provider)

    assert isinstance(runtime.video_indexer, CoarseVideoIndexer)
    assert runtime.worker.video_indexer is runtime.video_indexer


def test_semantic_search_runtime_rejects_invalid_embedding_dimensions(
    tmp_path: Path,
    monkeypatch,
) -> None:
    catalog = CatalogStore(tmp_path / "clipatlas.sqlite3")
    monkeypatch.setenv("CLIPATLAS_EMBEDDING_API_KEY", "embedding-key")
    monkeypatch.setenv("CLIPATLAS_EMBEDDING_DIMENSIONS", "0")

    with pytest.raises(ValueError, match="CLIPATLAS_EMBEDDING_DIMENSIONS"):
        build_semantic_search_service(catalog)

    monkeypatch.setenv("CLIPATLAS_EMBEDDING_DIMENSIONS", "not-an-integer")
    with pytest.raises(ValueError, match="CLIPATLAS_EMBEDDING_DIMENSIONS"):
        build_semantic_search_service(catalog)


def test_library_runtime_injects_semantic_indexer_when_embedding_is_configured(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CLIPATLAS_LIBRARY_DB", str(tmp_path / "library.sqlite3"))
    monkeypatch.setenv("CLIPATLAS_LIBRARY_CACHE_ROOT", str(tmp_path / "cache"))
    monkeypatch.setenv("CLIPATLAS_EMBEDDING_API_KEY", "embedding-key")
    monkeypatch.setenv("CLIPATLAS_EMBEDDING_BASE_URL", "https://example.test/compatible-mode/v1")
    monkeypatch.setenv("CLIPATLAS_EMBEDDING_DIMENSIONS", "768")

    runtime = build_library_runtime()

    assert isinstance(runtime.indexer, SemanticIndexer)
    assert runtime.worker.indexer is runtime.indexer


def test_library_runtime_keeps_indexing_disabled_without_embedding_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CLIPATLAS_LIBRARY_DB", str(tmp_path / "library.sqlite3"))
    monkeypatch.setenv("CLIPATLAS_LIBRARY_CACHE_ROOT", str(tmp_path / "cache"))
    monkeypatch.delenv("CLIPATLAS_EMBEDDING_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    runtime = build_library_runtime()

    assert runtime.indexer is None
    assert runtime.worker.indexer is None

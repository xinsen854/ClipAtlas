from pathlib import Path
from uuid import UUID

import pytest

import clipatlas.retrieval.search as search_module
from clipatlas.catalog.store import CatalogStore
from clipatlas.domain.models import VideoAsset
from clipatlas.embeddings.contracts import EmbeddingVector
from clipatlas.retrieval.models import VideoChunkEmbedding
from clipatlas.retrieval.video_profiles import COARSE_30S_PROFILE
from clipatlas.video.models import IngestedVideo, MediaMetadata


class RecordingVideoQueryProvider:
    name = "qwen-vl-video"
    model = "qwen3-vl-embedding"
    effective_dimensions = 3

    def __init__(self) -> None:
        self.queries: list[str] = []

    async def embed_query(self, text: str) -> EmbeddingVector:
        self.queries.append(text)
        return EmbeddingVector(values=[1.0, 0.0, 0.0])

    async def embed_video(self, video_path: Path) -> EmbeddingVector:
        raise AssertionError("search must not re-embed video chunks")


def _persist_video(store: CatalogStore, source: Path, *, duration_ms: int = 70_000) -> VideoAsset:
    video = VideoAsset(
        filename=source.name,
        source_uri=source.as_uri(),
        duration_ms=duration_ms,
        width=1920,
        height=1080,
        fps=25.0,
    )
    store.save_prepared_video(
        IngestedVideo(
            video=video,
            metadata=MediaMetadata(
                duration_ms=duration_ms,
                width=1920,
                height=1080,
                fps=25.0,
                video_codec="h264",
                has_audio=True,
            ),
            segments=[],
            frames_by_segment={},
        )
    )
    return video


def _save_chunk(
    store: CatalogStore,
    video_id: UUID,
    *,
    start_ms: int,
    end_ms: int,
    vector: list[float],
    provider: str = "qwen-vl-video",
    model: str = "qwen3-vl-embedding",
    dimensions: int = 3,
) -> None:
    store.save_video_chunk_embedding(
        VideoChunkEmbedding(
            video_id=video_id,
            start_ms=start_ms,
            end_ms=end_ms,
            provider=provider,
            model=model,
            dimensions=dimensions,
            chunk_duration_ms=COARSE_30S_PROFILE.chunk_duration_ms,
            overlap_ms=COARSE_30S_PROFILE.overlap_ms,
            vector=vector,
        )
    )


def _service_type():
    service_type = getattr(search_module, "CoarseVideoSearchService", None)
    assert service_type is not None, "CoarseVideoSearchService must be implemented"
    return service_type


@pytest.mark.asyncio
async def test_coarse_video_search_ranks_chunks_in_same_multimodal_embedding_space(
    tmp_path: Path,
) -> None:
    store = CatalogStore(tmp_path / "clipatlas.sqlite3")
    first_source = tmp_path / "first.mp4"
    second_source = tmp_path / "second.mp4"
    first_source.write_bytes(b"first")
    second_source.write_bytes(b"second")
    first_video = _persist_video(store, first_source)
    second_video = _persist_video(store, second_source)
    _save_chunk(
        store,
        first_video.id,
        start_ms=0,
        end_ms=30_000,
        vector=[0.95, 0.05, 0.0],
    )
    _save_chunk(
        store,
        first_video.id,
        start_ms=25_000,
        end_ms=55_000,
        vector=[0.2, 0.8, 0.0],
    )
    _save_chunk(
        store,
        second_video.id,
        start_ms=10_000,
        end_ms=40_000,
        vector=[0.8, 0.2, 0.0],
    )
    _save_chunk(
        store,
        second_video.id,
        start_ms=40_000,
        end_ms=70_000,
        vector=[1.0, 0.0, 0.0],
        model="other-video-model",
    )
    provider = RecordingVideoQueryProvider()
    service = _service_type()(store=store, provider=provider)

    hits = await service.search("一个人在街上奔跑", limit=3, profile=COARSE_30S_PROFILE)

    assert provider.queries == ["一个人在街上奔跑"]
    assert [(hit.video_id, hit.source_start_ms, hit.source_end_ms) for hit in hits] == [
        (first_video.id, 0, 30_000),
        (second_video.id, 10_000, 40_000),
        (first_video.id, 25_000, 55_000),
    ]
    assert hits[0].source_uri == first_video.source_uri
    assert hits[0].filename == first_video.filename
    assert hits[0].score > hits[1].score > hits[2].score
    assert all(hit.embedding_provider == provider.name for hit in hits)
    assert all(hit.embedding_model == provider.model for hit in hits)
    assert all(hit.embedding_dimensions == provider.effective_dimensions for hit in hits)


@pytest.mark.asyncio
async def test_coarse_video_search_respects_video_filter(tmp_path: Path) -> None:
    store = CatalogStore(tmp_path / "clipatlas.sqlite3")
    first_source = tmp_path / "first.mp4"
    second_source = tmp_path / "second.mp4"
    first_source.write_bytes(b"first")
    second_source.write_bytes(b"second")
    first_video = _persist_video(store, first_source)
    second_video = _persist_video(store, second_source)
    _save_chunk(store, first_video.id, start_ms=0, end_ms=30_000, vector=[1.0, 0.0, 0.0])
    _save_chunk(store, second_video.id, start_ms=0, end_ms=30_000, vector=[0.9, 0.1, 0.0])
    provider = RecordingVideoQueryProvider()
    service = _service_type()(store=store, provider=provider)

    hits = await service.search(
        "夜晚的城市道路",
        limit=10,
        video_ids=[second_video.id],
        profile=COARSE_30S_PROFILE,
    )

    assert len(hits) == 1
    assert hits[0].video_id == second_video.id


@pytest.mark.asyncio
async def test_non_positive_coarse_video_search_limit_skips_query_embedding(
    tmp_path: Path,
) -> None:
    store = CatalogStore(tmp_path / "clipatlas.sqlite3")
    provider = RecordingVideoQueryProvider()
    service = _service_type()(store=store, provider=provider)

    hits = await service.search("不会发送的查询", limit=0)

    assert hits == []
    assert provider.queries == []

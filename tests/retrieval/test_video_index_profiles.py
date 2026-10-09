from pathlib import Path
from uuid import uuid4

import pytest

from clipatlas.catalog.store import CatalogStore
from clipatlas.domain.models import VideoAsset
from clipatlas.embeddings.contracts import EmbeddingVector
from clipatlas.retrieval.models import VideoChunkEmbedding
from clipatlas.retrieval.search import CoarseVideoSearchService
from clipatlas.retrieval.video_profiles import (
    COARSE_30S_PROFILE,
    DEFAULT_VIDEO_INDEX_PROFILE,
    FINE_5S_PROFILE,
    VIDEO_INDEX_PROFILES,
)
from clipatlas.video.models import IngestedVideo, MediaMetadata


class FakeVideoEmbeddingProvider:
    name = "qwen-vl-video"
    model = "qwen3-vl-embedding"
    effective_dimensions = 3

    async def embed_query(self, text: str) -> EmbeddingVector:
        return EmbeddingVector(values=[1.0, 0.0, 0.0])

    async def embed_video(self, video_path: Path) -> EmbeddingVector:
        raise AssertionError("search must not re-embed chunks")


def _persist_video(store: CatalogStore) -> VideoAsset:
    video = VideoAsset(
        id=uuid4(),
        filename="sample.mp4",
        source_uri="file:///sample.mp4",
        duration_ms=40_000,
        width=1920,
        height=1080,
        fps=25.0,
    )
    store.save_prepared_video(
        IngestedVideo(
            video=video,
            metadata=MediaMetadata(
                duration_ms=40_000,
                width=1920,
                height=1080,
                fps=25.0,
                video_codec="h264",
                has_audio=False,
            ),
            segments=[],
            frames_by_segment={},
        )
    )
    return video


def test_only_supported_video_index_profiles_are_5s_and_30s() -> None:
    assert DEFAULT_VIDEO_INDEX_PROFILE is FINE_5S_PROFILE
    assert FINE_5S_PROFILE.chunk_duration_ms == 5_000
    assert FINE_5S_PROFILE.overlap_ms == 1_000
    assert COARSE_30S_PROFILE.chunk_duration_ms == 30_000
    assert COARSE_30S_PROFILE.overlap_ms == 5_000
    assert set(VIDEO_INDEX_PROFILES) == {"5s", "30s"}
    assert "1s" not in VIDEO_INDEX_PROFILES


def test_same_api_model_can_store_5s_and_30s_indexes_without_collision(tmp_path: Path) -> None:
    store = CatalogStore(tmp_path / "catalog.sqlite3")
    video = _persist_video(store)

    store.save_video_chunk_embedding(
        VideoChunkEmbedding(
            video_id=video.id,
            start_ms=0,
            end_ms=4_000,
            provider="qwen-vl-video",
            model="qwen3-vl-embedding",
            dimensions=3,
            chunk_duration_ms=5_000,
            overlap_ms=1_000,
            vector=[1.0, 0.0, 0.0],
        )
    )
    store.save_video_chunk_embedding(
        VideoChunkEmbedding(
            video_id=video.id,
            start_ms=0,
            end_ms=4_000,
            provider="qwen-vl-video",
            model="qwen3-vl-embedding",
            dimensions=3,
            chunk_duration_ms=30_000,
            overlap_ms=5_000,
            vector=[0.0, 1.0, 0.0],
        )
    )

    fine = store.list_video_chunk_embeddings_for_search(
        provider="qwen-vl-video",
        model="qwen3-vl-embedding",
        dimensions=3,
        chunk_duration_ms=5_000,
        overlap_ms=1_000,
    )
    coarse = store.list_video_chunk_embeddings_for_search(
        provider="qwen-vl-video",
        model="qwen3-vl-embedding",
        dimensions=3,
        chunk_duration_ms=30_000,
        overlap_ms=5_000,
    )

    assert len(fine) == 1
    assert len(coarse) == 1
    assert fine[0].vector == [1.0, 0.0, 0.0]
    assert coarse[0].vector == [0.0, 1.0, 0.0]


@pytest.mark.asyncio
async def test_video_search_defaults_to_5s_and_can_explicitly_search_30s(tmp_path: Path) -> None:
    store = CatalogStore(tmp_path / "catalog.sqlite3")
    video = _persist_video(store)
    for profile, vector in (
        (FINE_5S_PROFILE, [0.8, 0.2, 0.0]),
        (COARSE_30S_PROFILE, [1.0, 0.0, 0.0]),
    ):
        store.save_video_chunk_embedding(
            VideoChunkEmbedding(
                video_id=video.id,
                start_ms=0,
                end_ms=4_000,
                provider="qwen-vl-video",
                model="qwen3-vl-embedding",
                dimensions=3,
                chunk_duration_ms=profile.chunk_duration_ms,
                overlap_ms=profile.overlap_ms,
                vector=vector,
            )
        )

    service = CoarseVideoSearchService(store=store, provider=FakeVideoEmbeddingProvider())

    fine_hits = await service.search("车辆行驶")
    coarse_hits = await service.search("车辆行驶", profile=COARSE_30S_PROFILE)

    assert len(fine_hits) == 1
    assert fine_hits[0].chunk_duration_ms == 5_000
    assert fine_hits[0].overlap_ms == 1_000
    assert len(coarse_hits) == 1
    assert coarse_hits[0].chunk_duration_ms == 30_000
    assert coarse_hits[0].overlap_ms == 5_000

from pathlib import Path

import pytest

from clipatlas.catalog.store import CatalogStore
from clipatlas.domain.models import (
    AnnotationOrigin,
    SegmentSource,
    SemanticAnnotation,
    VideoAsset,
    VideoSegment,
)
from clipatlas.embeddings.contracts import EmbeddingVector
from clipatlas.retrieval.models import SegmentEmbedding
from clipatlas.retrieval.search import SemanticSearchService
from clipatlas.video.models import IngestedVideo, MediaMetadata


class FakeSearchEmbeddingProvider:
    def __init__(self, query_vector: list[float]) -> None:
        self._query_vector = query_vector
        self.query_calls: list[str] = []

    @property
    def name(self) -> str:
        return "fake-embedding"

    @property
    def model(self) -> str:
        return "embed-v1"

    @property
    def dimensions(self) -> int:
        return len(self._query_vector)

    async def embed_documents(self, texts: list[str]) -> list[EmbeddingVector]:
        raise AssertionError("search must not embed documents")

    async def embed_query(self, text: str) -> EmbeddingVector:
        self.query_calls.append(text)
        return EmbeddingVector(values=list(self._query_vector))


def _save_searchable_segment(
    store: CatalogStore,
    *,
    filename: str,
    source_uri: str,
    start_ms: int,
    end_ms: int,
    description: str,
    vector: list[float],
) -> tuple[VideoAsset, VideoSegment, SemanticAnnotation]:
    video = VideoAsset(
        filename=filename,
        source_uri=source_uri,
        duration_ms=max(end_ms + 1_000, 10_000),
        width=1920,
        height=1080,
        fps=25.0,
    )
    segment = VideoSegment(
        video_id=video.id,
        start_ms=start_ms,
        end_ms=end_ms,
        source=SegmentSource.SCENE_DETECTION,
    )
    store.save_prepared_video(
        IngestedVideo(
            video=video,
            metadata=MediaMetadata(
                duration_ms=video.duration_ms,
                width=video.width,
                height=video.height,
                fps=video.fps,
                video_codec="h264",
                has_audio=False,
            ),
            segments=[segment],
            frames_by_segment={segment.id: []},
        )
    )
    annotation = SemanticAnnotation(
        segment_id=segment.id,
        origin=AnnotationOrigin.AI,
        provider="qwen",
        model="qwen3.7-flash",
        description=description,
        revision=1,
    )
    store.save_annotation(annotation)
    store.save_embedding(
        SegmentEmbedding(
            segment_id=segment.id,
            annotation_id=annotation.id,
            annotation_revision=annotation.revision,
            provider="fake-embedding",
            model="embed-v1",
            dimensions=len(vector),
            vector=vector,
        )
    )
    return video, segment, annotation


@pytest.mark.asyncio
async def test_search_sorts_by_cosine_and_returns_exact_canonical_source_ranges(
    tmp_path: Path,
) -> None:
    store = CatalogStore(tmp_path / "clipatlas.sqlite3")
    best_video, best_segment, best_annotation = _save_searchable_segment(
        store,
        filename="rain.mp4",
        source_uri="file:///media/rain.mp4",
        start_ms=12_345,
        end_ms=18_765,
        description="一个男人独自在雨夜街头行走",
        vector=[1.0, 0.0, 0.0],
    )
    _, second_segment, _ = _save_searchable_segment(
        store,
        filename="crowd.mp4",
        source_uri="file:///media/crowd.mp4",
        start_ms=2_000,
        end_ms=6_000,
        description="城市人群穿过街道",
        vector=[0.8, 0.6, 0.0],
    )
    provider = FakeSearchEmbeddingProvider([1.0, 0.0, 0.0])
    service = SemanticSearchService(store=store, provider=provider)

    hits = await service.search("孤独男人在雨里走路")

    assert provider.query_calls == ["孤独男人在雨里走路"]
    assert [hit.segment_id for hit in hits] == [best_segment.id, second_segment.id]
    assert hits[0].video_id == best_video.id
    assert hits[0].source_uri == best_video.source_uri
    assert hits[0].source_start_ms == best_segment.start_ms
    assert hits[0].source_end_ms == best_segment.end_ms
    assert hits[0].effective_description == best_annotation.description
    assert hits[0].annotation.id == best_annotation.id
    assert hits[0].embedding_provider == provider.name
    assert hits[0].embedding_model == provider.model
    assert hits[0].embedding_dimensions == provider.dimensions
    assert hits[0].score == pytest.approx(1.0)
    assert hits[1].score == pytest.approx(0.8)


@pytest.mark.asyncio
async def test_search_respects_limit_and_video_filter(tmp_path: Path) -> None:
    store = CatalogStore(tmp_path / "clipatlas.sqlite3")
    first_video, first_segment, _ = _save_searchable_segment(
        store,
        filename="first.mp4",
        source_uri="file:///media/first.mp4",
        start_ms=0,
        end_ms=4_000,
        description="First",
        vector=[1.0, 0.0, 0.0],
    )
    second_video, second_segment, _ = _save_searchable_segment(
        store,
        filename="second.mp4",
        source_uri="file:///media/second.mp4",
        start_ms=5_000,
        end_ms=9_000,
        description="Second",
        vector=[0.9, 0.1, 0.0],
    )
    service = SemanticSearchService(
        store=store,
        provider=FakeSearchEmbeddingProvider([1.0, 0.0, 0.0]),
    )

    limited = await service.search("query", limit=1)
    filtered = await service.search("query", video_ids=[second_video.id])

    assert [hit.segment_id for hit in limited] == [first_segment.id]
    assert [hit.segment_id for hit in filtered] == [second_segment.id]
    assert all(hit.video_id != first_video.id for hit in filtered)


@pytest.mark.asyncio
async def test_search_skips_zero_norm_and_stale_embeddings(tmp_path: Path) -> None:
    store = CatalogStore(tmp_path / "clipatlas.sqlite3")
    _, zero_segment, _ = _save_searchable_segment(
        store,
        filename="zero.mp4",
        source_uri="file:///media/zero.mp4",
        start_ms=0,
        end_ms=4_000,
        description="Zero vector",
        vector=[0.0, 0.0, 0.0],
    )
    _, stale_segment, _ = _save_searchable_segment(
        store,
        filename="stale.mp4",
        source_uri="file:///media/stale.mp4",
        start_ms=5_000,
        end_ms=9_000,
        description="Old AI meaning",
        vector=[1.0, 0.0, 0.0],
    )
    store.save_annotation(
        SemanticAnnotation(
            segment_id=stale_segment.id,
            origin=AnnotationOrigin.HUMAN,
            description="人工已经改成新的含义",
            revision=2,
        )
    )
    _, valid_segment, _ = _save_searchable_segment(
        store,
        filename="valid.mp4",
        source_uri="file:///media/valid.mp4",
        start_ms=10_000,
        end_ms=14_000,
        description="Current searchable meaning",
        vector=[0.7, 0.7, 0.0],
    )
    service = SemanticSearchService(
        store=store,
        provider=FakeSearchEmbeddingProvider([1.0, 0.0, 0.0]),
    )

    hits = await service.search("query")

    assert [hit.segment_id for hit in hits] == [valid_segment.id]
    assert zero_segment.id not in {hit.segment_id for hit in hits}
    assert stale_segment.id not in {hit.segment_id for hit in hits}


@pytest.mark.asyncio
async def test_search_returns_empty_for_non_positive_limit_without_embedding_query(
    tmp_path: Path,
) -> None:
    store = CatalogStore(tmp_path / "clipatlas.sqlite3")
    provider = FakeSearchEmbeddingProvider([1.0, 0.0, 0.0])
    service = SemanticSearchService(store=store, provider=provider)

    assert await service.search("query", limit=0) == []
    assert provider.query_calls == []

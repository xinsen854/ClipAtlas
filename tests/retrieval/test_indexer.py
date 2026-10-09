import sqlite3
from pathlib import Path
from uuid import UUID

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
from clipatlas.retrieval.indexer import SemanticIndexer
from clipatlas.video.models import IngestedVideo, MediaMetadata


class FakeEmbeddingProvider:
    def __init__(self, *, model: str = "embed-v1", dimensions: int = 3) -> None:
        self._model = model
        self._dimensions = dimensions
        self.document_calls: list[list[str]] = []

    @property
    def name(self) -> str:
        return "fake-embedding"

    @property
    def model(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed_documents(self, texts: list[str]) -> list[EmbeddingVector]:
        self.document_calls.append(list(texts))
        values = [1.0] + [0.0] * (self._dimensions - 1)
        return [EmbeddingVector(values=values) for _ in texts]

    async def embed_query(self, text: str) -> EmbeddingVector:
        values = [1.0] + [0.0] * (self._dimensions - 1)
        return EmbeddingVector(values=values)


def _save_segment(store: CatalogStore, *, start_ms: int = 0) -> VideoSegment:
    video = VideoAsset(
        filename=f"movie-{start_ms}.mp4",
        source_uri=f"file:///media/movie-{start_ms}.mp4",
        duration_ms=10_000,
        width=1920,
        height=1080,
        fps=25.0,
    )
    segment = VideoSegment(
        video_id=video.id,
        start_ms=start_ms,
        end_ms=start_ms + 4_000,
        source=SegmentSource.SCENE_DETECTION,
    )
    store.save_prepared_video(
        IngestedVideo(
            video=video,
            metadata=MediaMetadata(
                duration_ms=10_000,
                width=1920,
                height=1080,
                fps=25.0,
                video_codec="h264",
                has_audio=False,
            ),
            segments=[segment],
            frames_by_segment={segment.id: []},
        )
    )
    return segment


def _save_annotation(
    store: CatalogStore,
    segment_id: UUID,
    *,
    origin: AnnotationOrigin,
    revision: int,
    description: str,
) -> SemanticAnnotation:
    annotation = SemanticAnnotation(
        segment_id=segment_id,
        origin=origin,
        provider="qwen" if origin is AnnotationOrigin.AI else None,
        model="qwen3.7-flash" if origin is AnnotationOrigin.AI else None,
        description=description,
        revision=revision,
    )
    store.save_annotation(annotation)
    return annotation


@pytest.mark.asyncio
async def test_index_segment_embeds_effective_ai_annotation(tmp_path: Path) -> None:
    store = CatalogStore(tmp_path / "clipatlas.sqlite3")
    segment = _save_segment(store)
    annotation = _save_annotation(
        store,
        segment.id,
        origin=AnnotationOrigin.AI,
        revision=1,
        description="A man walks alone in rain",
    )
    provider = FakeEmbeddingProvider()
    indexer = SemanticIndexer(store=store, provider=provider)

    generated = await indexer.index_segment(segment.id)

    assert generated is True
    assert provider.document_calls == [["A man walks alone in rain"]]
    embedding = store.get_effective_embedding(
        segment.id,
        provider=provider.name,
        model=provider.model,
        dimensions=provider.dimensions,
    )
    assert embedding is not None
    assert embedding.annotation_id == annotation.id
    assert embedding.annotation_revision == annotation.revision
    assert embedding.vector == [1.0, 0.0, 0.0]


@pytest.mark.asyncio
async def test_index_segment_skips_unchanged_effective_signature(tmp_path: Path) -> None:
    store = CatalogStore(tmp_path / "clipatlas.sqlite3")
    segment = _save_segment(store)
    _save_annotation(
        store,
        segment.id,
        origin=AnnotationOrigin.AI,
        revision=1,
        description="A man waits at a bus stop",
    )
    provider = FakeEmbeddingProvider()
    indexer = SemanticIndexer(store=store, provider=provider)

    assert await indexer.index_segment(segment.id) is True
    assert await indexer.index_segment(segment.id) is False

    assert provider.document_calls == [["A man waits at a bus stop"]]


@pytest.mark.asyncio
async def test_human_correction_reindexes_and_keeps_old_vector_history(tmp_path: Path) -> None:
    db_path = tmp_path / "clipatlas.sqlite3"
    store = CatalogStore(db_path)
    segment = _save_segment(store)
    ai = _save_annotation(
        store,
        segment.id,
        origin=AnnotationOrigin.AI,
        revision=1,
        description="A man looks sad in rain",
    )
    provider = FakeEmbeddingProvider()
    indexer = SemanticIndexer(store=store, provider=provider)
    assert await indexer.index_segment(segment.id) is True

    human = _save_annotation(
        store,
        segment.id,
        origin=AnnotationOrigin.HUMAN,
        revision=2,
        description="一个男人独自在雨中等待",
    )

    assert await indexer.index_segment(segment.id) is True
    assert provider.document_calls == [
        ["A man looks sad in rain"],
        ["一个男人独自在雨中等待"],
    ]
    effective = store.get_effective_embedding(
        segment.id,
        provider=provider.name,
        model=provider.model,
        dimensions=provider.dimensions,
    )
    assert effective is not None
    assert effective.annotation_id == human.id

    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT annotation_id, effective
            FROM catalog_embeddings
            WHERE segment_id = ?
            ORDER BY rowid
            """,
            (str(segment.id),),
        ).fetchall()
    assert rows == [(str(ai.id), 0), (str(human.id), 1)]


@pytest.mark.asyncio
async def test_model_or_dimension_change_forces_reindex(tmp_path: Path) -> None:
    store = CatalogStore(tmp_path / "clipatlas.sqlite3")
    segment = _save_segment(store)
    _save_annotation(
        store,
        segment.id,
        origin=AnnotationOrigin.AI,
        revision=1,
        description="Crowd crosses a city street",
    )
    first_provider = FakeEmbeddingProvider(model="embed-v1", dimensions=3)
    second_provider = FakeEmbeddingProvider(model="embed-v2", dimensions=2)

    assert await SemanticIndexer(store=store, provider=first_provider).index_segment(segment.id)
    assert await SemanticIndexer(store=store, provider=second_provider).index_segment(segment.id)

    assert second_provider.document_calls == [["Crowd crosses a city street"]]
    effective = store.get_effective_embedding(
        segment.id,
        provider=second_provider.name,
        model=second_provider.model,
        dimensions=second_provider.dimensions,
    )
    assert effective is not None
    assert effective.vector == [1.0, 0.0]


@pytest.mark.asyncio
async def test_index_segment_skips_when_no_annotation_exists(tmp_path: Path) -> None:
    store = CatalogStore(tmp_path / "clipatlas.sqlite3")
    segment = _save_segment(store)
    provider = FakeEmbeddingProvider()
    indexer = SemanticIndexer(store=store, provider=provider)

    assert await indexer.index_segment(segment.id) is False
    assert provider.document_calls == []


@pytest.mark.asyncio
async def test_index_pending_indexes_only_segments_that_need_vectors(tmp_path: Path) -> None:
    store = CatalogStore(tmp_path / "clipatlas.sqlite3")
    first = _save_segment(store, start_ms=0)
    second = _save_segment(store, start_ms=5_000)
    _save_annotation(
        store,
        first.id,
        origin=AnnotationOrigin.AI,
        revision=1,
        description="First searchable shot",
    )
    provider = FakeEmbeddingProvider()
    indexer = SemanticIndexer(store=store, provider=provider)

    assert await indexer.index_pending() == 1
    assert await indexer.index_pending(limit=1) == 0
    assert provider.document_calls == [["First searchable shot"]]
    assert second.id in store.list_segment_ids()

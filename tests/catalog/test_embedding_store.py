import sqlite3
from pathlib import Path

from clipatlas.catalog.store import CatalogStore
from clipatlas.domain.models import (
    AnnotationOrigin,
    SegmentSource,
    SemanticAnnotation,
    VideoAsset,
    VideoSegment,
)
from clipatlas.retrieval.models import SegmentEmbedding
from clipatlas.video.models import IngestedVideo, MediaMetadata


def _persist_segment_and_annotation(
    store: CatalogStore,
) -> tuple[VideoSegment, SemanticAnnotation]:
    video = VideoAsset(
        filename="movie.mp4",
        source_uri="file:///media/movie.mp4",
        duration_ms=10_000,
        width=1920,
        height=1080,
        fps=25.0,
    )
    segment = VideoSegment(
        video_id=video.id,
        start_ms=1_000,
        end_ms=5_000,
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
    annotation = SemanticAnnotation(
        segment_id=segment.id,
        origin=AnnotationOrigin.AI,
        provider="qwen",
        model="qwen3.7-flash",
        description="A man walks alone in rain",
        revision=1,
    )
    store.save_annotation(annotation)
    return segment, annotation


def test_embedding_persists_across_reopen(tmp_path: Path) -> None:
    db_path = tmp_path / "clipatlas.sqlite3"
    store = CatalogStore(db_path)
    segment, annotation = _persist_segment_and_annotation(store)
    record = SegmentEmbedding(
        segment_id=segment.id,
        annotation_id=annotation.id,
        annotation_revision=annotation.revision,
        provider="qwen-embedding",
        model="text-embedding-v4",
        dimensions=3,
        vector=[1.0, 0.25, -0.5],
    )

    store.save_embedding(record)
    loaded = CatalogStore(db_path).get_effective_embedding(
        segment.id,
        provider="qwen-embedding",
        model="text-embedding-v4",
        dimensions=3,
    )

    assert loaded == record


def test_new_effective_embedding_deactivates_but_does_not_delete_history(tmp_path: Path) -> None:
    db_path = tmp_path / "clipatlas.sqlite3"
    store = CatalogStore(db_path)
    segment, annotation = _persist_segment_and_annotation(store)
    first = SegmentEmbedding(
        segment_id=segment.id,
        annotation_id=annotation.id,
        annotation_revision=1,
        provider="qwen-embedding",
        model="text-embedding-v4",
        dimensions=3,
        vector=[1.0, 0.0, 0.0],
    )
    corrected = SemanticAnnotation(
        segment_id=segment.id,
        origin=AnnotationOrigin.HUMAN,
        description="一个男人独自在雨中行走",
        revision=2,
    )
    store.save_annotation(corrected)
    second = SegmentEmbedding(
        segment_id=segment.id,
        annotation_id=corrected.id,
        annotation_revision=2,
        provider="qwen-embedding",
        model="text-embedding-v4",
        dimensions=3,
        vector=[0.0, 1.0, 0.0],
    )

    store.save_embedding(first)
    store.save_embedding(second)

    effective = store.get_effective_embedding(
        segment.id,
        provider="qwen-embedding",
        model="text-embedding-v4",
        dimensions=3,
    )
    assert effective == second

    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT id, effective FROM catalog_embeddings WHERE segment_id = ? ORDER BY rowid",
            (str(segment.id),),
        ).fetchall()
    assert rows == [(str(first.id), 0), (str(second.id), 1)]


def test_provider_model_or_dimension_change_does_not_collide(tmp_path: Path) -> None:
    db_path = tmp_path / "clipatlas.sqlite3"
    store = CatalogStore(db_path)
    segment, annotation = _persist_segment_and_annotation(store)
    old = SegmentEmbedding(
        segment_id=segment.id,
        annotation_id=annotation.id,
        annotation_revision=annotation.revision,
        provider="qwen-embedding",
        model="text-embedding-v4",
        dimensions=3,
        vector=[1.0, 0.0, 0.0],
    )
    new = SegmentEmbedding(
        segment_id=segment.id,
        annotation_id=annotation.id,
        annotation_revision=annotation.revision,
        provider="other-embedding",
        model="model-v2",
        dimensions=2,
        vector=[0.0, 1.0],
    )

    store.save_embedding(old)
    store.save_embedding(new)

    assert (
        store.get_effective_embedding(
            segment.id,
            provider="qwen-embedding",
            model="text-embedding-v4",
            dimensions=3,
        )
        is None
    )
    assert (
        store.get_effective_embedding(
            segment.id,
            provider="other-embedding",
            model="model-v2",
            dimensions=2,
        )
        == new
    )
    assert store.list_effective_embeddings(
        provider="other-embedding",
        model="model-v2",
        dimensions=2,
    ) == [new]


def test_deactivate_segment_embeddings_clears_effective_record(tmp_path: Path) -> None:
    store = CatalogStore(tmp_path / "clipatlas.sqlite3")
    segment, annotation = _persist_segment_and_annotation(store)
    record = SegmentEmbedding(
        segment_id=segment.id,
        annotation_id=annotation.id,
        annotation_revision=annotation.revision,
        provider="qwen-embedding",
        model="text-embedding-v4",
        dimensions=3,
        vector=[1.0, 0.0, 0.0],
    )
    store.save_embedding(record)

    store.deactivate_segment_embeddings(segment.id)

    assert (
        store.get_effective_embedding(
            segment.id,
            provider="qwen-embedding",
            model="text-embedding-v4",
            dimensions=3,
        )
        is None
    )

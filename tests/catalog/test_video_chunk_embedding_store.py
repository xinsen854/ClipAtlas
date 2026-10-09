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
from clipatlas.retrieval.models import SegmentEmbedding, VideoChunkEmbedding
from clipatlas.video.models import IngestedVideo, MediaMetadata

_CHUNK_DURATION_MS = 30_000
_OVERLAP_MS = 5_000


def _persist_video(store: CatalogStore, *, with_segment: bool = False) -> tuple[VideoAsset, VideoSegment | None]:
    video = VideoAsset(
        filename="movie.mp4",
        source_uri="file:///media/movie.mp4",
        duration_ms=70_000,
        width=1920,
        height=1080,
        fps=25.0,
    )
    segment = (
        VideoSegment(
            video_id=video.id,
            start_ms=1_000,
            end_ms=5_000,
            source=SegmentSource.SCENE_DETECTION,
        )
        if with_segment
        else None
    )
    segments = [segment] if segment is not None else []
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
            segments=segments,
            frames_by_segment={segment.id: []} if segment is not None else {},
        )
    )
    return video, segment


def _video_embedding(video: VideoAsset, start_ms: int, end_ms: int, marker: float) -> VideoChunkEmbedding:
    return VideoChunkEmbedding(
        video_id=video.id,
        start_ms=start_ms,
        end_ms=end_ms,
        provider="qwen-vl-video",
        model="qwen3-vl-embedding",
        dimensions=2560,
        chunk_duration_ms=_CHUNK_DURATION_MS,
        overlap_ms=_OVERLAP_MS,
        vector=[marker] + [0.0] * 2559,
    )


def test_video_chunk_embedding_persists_across_reopen(tmp_path: Path) -> None:
    db_path = tmp_path / "clipatlas.sqlite3"
    store = CatalogStore(db_path)
    video, _ = _persist_video(store)
    record = _video_embedding(video, 0, 30_000, 1.0)

    store.save_video_chunk_embedding(record)
    loaded = CatalogStore(db_path).get_video_chunk_embedding(
        video.id,
        start_ms=0,
        end_ms=30_000,
        provider="qwen-vl-video",
        model="qwen3-vl-embedding",
        dimensions=2560,
        chunk_duration_ms=_CHUNK_DURATION_MS,
        overlap_ms=_OVERLAP_MS,
    )

    assert loaded == record


def test_same_video_chunk_namespace_is_upserted_not_duplicated(tmp_path: Path) -> None:
    db_path = tmp_path / "clipatlas.sqlite3"
    store = CatalogStore(db_path)
    video, _ = _persist_video(store)
    first = _video_embedding(video, 0, 30_000, 1.0)
    replacement = _video_embedding(video, 0, 30_000, 2.0)

    store.save_video_chunk_embedding(first)
    store.save_video_chunk_embedding(replacement)

    loaded = store.get_video_chunk_embedding(
        video.id,
        start_ms=0,
        end_ms=30_000,
        provider="qwen-vl-video",
        model="qwen3-vl-embedding",
        dimensions=2560,
        chunk_duration_ms=_CHUNK_DURATION_MS,
        overlap_ms=_OVERLAP_MS,
    )
    assert loaded == replacement
    with sqlite3.connect(db_path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM catalog_video_chunk_embeddings").fetchone()[0]
    assert count == 1


def test_video_embeddings_are_listed_in_time_order(tmp_path: Path) -> None:
    store = CatalogStore(tmp_path / "clipatlas.sqlite3")
    video, _ = _persist_video(store)
    later = _video_embedding(video, 25_000, 55_000, 2.0)
    earlier = _video_embedding(video, 0, 30_000, 1.0)

    store.save_video_chunk_embedding(later)
    store.save_video_chunk_embedding(earlier)

    assert store.list_video_chunk_embeddings(
        video.id,
        provider="qwen-vl-video",
        model="qwen3-vl-embedding",
        dimensions=2560,
        chunk_duration_ms=_CHUNK_DURATION_MS,
        overlap_ms=_OVERLAP_MS,
    ) == [earlier, later]


def test_video_embedding_does_not_deactivate_existing_text_embedding(tmp_path: Path) -> None:
    store = CatalogStore(tmp_path / "clipatlas.sqlite3")
    video, segment = _persist_video(store, with_segment=True)
    assert segment is not None
    annotation = SemanticAnnotation(
        segment_id=segment.id,
        origin=AnnotationOrigin.AI,
        provider="qwen",
        model="gpt-5.6-sol",
        description="A vehicle drives on a mountain road",
        revision=1,
    )
    store.save_annotation(annotation)
    text_record = SegmentEmbedding(
        segment_id=segment.id,
        annotation_id=annotation.id,
        annotation_revision=1,
        provider="qwen-embedding",
        model="text-embedding-v4",
        dimensions=1024,
        vector=[1.0] + [0.0] * 1023,
    )
    store.save_embedding(text_record)

    store.save_video_chunk_embedding(_video_embedding(video, 0, 30_000, 1.0))

    assert store.get_effective_embedding(
        segment.id,
        provider="qwen-embedding",
        model="text-embedding-v4",
        dimensions=1024,
    ) == text_record

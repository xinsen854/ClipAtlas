from pathlib import Path
from uuid import UUID, uuid4

from clipatlas.catalog.store import CatalogStore
from clipatlas.domain.models import (
    AnnotationOrigin,
    SegmentSource,
    SemanticAnnotation,
    VideoAsset,
    VideoSegment,
)
from clipatlas.retrieval.semantics import build_retrieval_text
from clipatlas.video.models import IngestedVideo, MediaMetadata


def _persist_segment(store: CatalogStore) -> UUID:
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
        start_ms=0,
        end_ms=10_000,
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
    return segment.id


def _save_annotation(
    store: CatalogStore,
    segment_id: UUID,
    *,
    origin: AnnotationOrigin,
    description: str,
    revision: int,
) -> SemanticAnnotation:
    annotation = SemanticAnnotation(
        segment_id=segment_id,
        origin=origin,
        description=description,
        revision=revision,
    )
    store.save_annotation(annotation)
    return annotation


def test_effective_annotation_prefers_latest_human_revision(tmp_path: Path) -> None:
    store = CatalogStore(tmp_path / "clipatlas.sqlite3")
    segment_id = _persist_segment(store)
    _save_annotation(
        store,
        segment_id,
        origin=AnnotationOrigin.AI,
        description="AI first meaning",
        revision=1,
    )
    _save_annotation(
        store,
        segment_id,
        origin=AnnotationOrigin.HUMAN,
        description="Human earlier meaning",
        revision=1,
    )
    latest_human = _save_annotation(
        store,
        segment_id,
        origin=AnnotationOrigin.HUMAN,
        description="Human corrected meaning",
        revision=2,
    )

    effective = store.get_effective_annotation(segment_id)

    assert effective is not None
    assert effective.id == latest_human.id
    assert effective.description == "Human corrected meaning"


def test_effective_annotation_uses_latest_ai_when_no_human_exists(tmp_path: Path) -> None:
    store = CatalogStore(tmp_path / "clipatlas.sqlite3")
    segment_id = _persist_segment(store)
    _save_annotation(
        store,
        segment_id,
        origin=AnnotationOrigin.AI,
        description="AI first meaning",
        revision=1,
    )
    latest_ai = _save_annotation(
        store,
        segment_id,
        origin=AnnotationOrigin.AI,
        description="AI improved meaning",
        revision=2,
    )

    effective = store.get_effective_annotation(segment_id)

    assert effective is not None
    assert effective.id == latest_ai.id


def test_retrieval_text_is_deterministic_and_omits_empty_fields() -> None:
    annotation = SemanticAnnotation(
        segment_id=uuid4(),
        origin=AnnotationOrigin.HUMAN,
        description="男人站在雨夜街口",
        characters=["男人"],
        actions=["等待"],
        scene=["城市雨夜"],
        emotions=["孤独"],
        objects=["雨伞", "路灯"],
        ocr=[],
        shot_type="medium shot",
        camera_motion="static",
    )

    assert build_retrieval_text(annotation) == (
        "男人站在雨夜街口\n"
        "人物: 男人\n"
        "动作: 等待\n"
        "场景: 城市雨夜\n"
        "情绪: 孤独\n"
        "物体: 雨伞, 路灯\n"
        "景别: medium shot\n"
        "运镜: static"
    )

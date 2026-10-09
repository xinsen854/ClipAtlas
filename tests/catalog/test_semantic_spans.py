from pathlib import Path

from clipatlas.catalog.store import CatalogStore
from clipatlas.domain.models import (
    AnnotationOrigin,
    SegmentSource,
    SemanticAnnotation,
    VideoAsset,
    VideoSegment,
)
from clipatlas.video.models import IngestedVideo, MediaMetadata


def test_semantic_span_expands_evidence_without_crossing_title_card(tmp_path: Path) -> None:
    store = CatalogStore(tmp_path / "library.sqlite3")
    video = VideoAsset(
        filename="story.mp4", source_uri="file:///story.mp4", duration_ms=8000,
        width=1920, height=1080, fps=25,
    )
    segments = [
        VideoSegment(video_id=video.id, start_ms=0, end_ms=2000,
                     source=SegmentSource.SCENE_DETECTION),
        VideoSegment(video_id=video.id, start_ms=2000, end_ms=5000,
                     source=SegmentSource.SCENE_DETECTION),
        VideoSegment(video_id=video.id, start_ms=5000, end_ms=8000,
                     source=SegmentSource.SCENE_DETECTION),
    ]
    store.save_prepared_video(IngestedVideo(
        video=video,
        metadata=MediaMetadata(
            duration_ms=8000, width=1920, height=1080, fps=25,
            video_codec="h264", has_audio=False,
        ),
        segments=segments,
        frames_by_segment={segment.id: [] for segment in segments},
    ))
    for segment, description, medium in zip(
        segments,
        ["越野车通过山路", "越野车继续通过泥泞山路", "黑底产品标题"],
        ["scene", "scene", "title_card"],
        strict=True,
    ):
        store.save_annotation(SemanticAnnotation(
            segment_id=segment.id, origin=AnnotationOrigin.AI,
            description=description, objects=["越野车"], scene=["山路"],
        ))
        store.save_segment_media_type(
            segment_id=segment.id, subject_medium=medium,
            text_ratio=0.05 if medium == "scene" else 0.5,
            text_block_count=1, has_real_subject=medium == "scene", basis="test",
        )

    assert store.rebuild_semantic_spans(video.id) == 2
    span = store.get_semantic_span_for_segment(segments[0].id)
    assert span is not None
    assert (span.safe_start_ms, span.safe_end_ms) == (0, 5000)
    assert span.objects == ["越野车"]
    assert span.scenes == ["山路"]
    assert span.anchor_ranges == [(0, 2000), (2000, 5000)]
    assert span.presentation_type is None
    assert store.expand_segment_window(segments[0].id, 4500) == (0, 4500)

    blocked = store.get_semantic_span_for_segment(segments[2].id)
    assert blocked is not None and blocked.pollution_level == "blocked"
    assert store.expand_segment_window(segments[2].id, 3000) is None

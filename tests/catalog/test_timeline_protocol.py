from pathlib import Path
from uuid import uuid4

from clipatlas.catalog.store import CatalogStore
from clipatlas.catalog.timeline import build_sequence_windows, build_timeline_events
from clipatlas.domain.evidence import EvidenceStatement, Proposition
from clipatlas.domain.visual_protocol import VideoTimelineEvent
from clipatlas.domain.models import (
    AnnotationOrigin,
    ObjectiveFact,
    ObjectiveFactLayer,
    SegmentSource,
    SemanticAnnotation,
    VideoSegment,
)


def test_rebuild_timeline_protocol_persists_events_and_windows(tmp_path: Path):
    store = CatalogStore(tmp_path / "library.sqlite3")
    video_id = uuid4()
    segment_id = uuid4()
    annotation_id = uuid4()
    with store._connect() as connection:
        connection.execute(
            "INSERT INTO catalog_videos (id,filename,source_uri,duration_ms,width,height,fps,video_codec,has_audio,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (str(video_id), "test.mp4", "file:///test.mp4", 4000, 1920, 1080, 25.0, "h264", 1, "2026-01-01T00:00:00+00:00"),
        )
        connection.execute(
            "INSERT INTO catalog_segments (id,video_id,start_ms,end_ms,source,created_at) VALUES (?,?,?,?,?,?)",
            (str(segment_id), str(video_id), 0, 4000, SegmentSource.AI.value, "2026-01-01T00:00:00+00:00"),
        )
    store.save_annotation(SemanticAnnotation(
        id=annotation_id,
        segment_id=segment_id,
        origin=AnnotationOrigin.AI,
        description="泰钽700行驶",
        facts=[ObjectiveFact(
            layer=ObjectiveFactLayer.ACTION,
            value="行驶",
            start_ms=1000,
            end_ms=3000,
            statement=EvidenceStatement(
                proposition=Proposition(subject="泰钽700", predicate="action", value="行驶"),
                entity_id="vehicle-1",
                kind="visual",
                representation="real_scene",
                frame_ids=["frame_0", "frame_1"],
                temporal_basis="interval",
            ),
        )],
    ))

    events, windows = store.rebuild_timeline_protocol(video_id)
    assert (events, windows) == (1, 1)
    assert store.list_timeline_events(video_id)[0].entity_id == f"{segment_id}:vehicle-1"
    assert store.list_sequence_windows(video_id)[0].continuity_status == "unknown_continuity"


def test_legacy_annotation_becomes_unknown_recall_event():
    video_id = uuid4()
    segment = VideoSegment(
        id=uuid4(), video_id=video_id, start_ms=0, end_ms=3000, source=SegmentSource.AI,
    )
    annotation = SemanticAnnotation(
        segment_id=segment.id, origin=AnnotationOrigin.AI,
        description="legacy", characters=["泰钽700"], actions=["行驶"],
    )
    events = build_timeline_events(segment, annotation)
    assert len(events) == 1
    assert events[0].action == "行驶"
    assert events[0].entity_id is None
    assert "entity_id" in events[0].unknown_fields


def test_overlapping_facts_are_aggregated_into_one_complete_event():
    video_id = uuid4()
    segment = VideoSegment(
        id=uuid4(), video_id=video_id, start_ms=0, end_ms=4000, source=SegmentSource.AI,
    )

    def statement(predicate: str, value: str) -> EvidenceStatement:
        return EvidenceStatement(
            proposition=Proposition(subject="泰钽700", predicate=predicate, value=value),
            entity_id="car_1",
            kind="visual",
            representation="real_scene",
            frame_ids=["frame_0", "frame_1"],
            temporal_basis="interval",
        )

    annotation = SemanticAnnotation(
        segment_id=segment.id,
        origin=AnnotationOrigin.AI,
        description="泰钽700在山路爬坡",
        facts=[
            ObjectiveFact(
                layer=ObjectiveFactLayer.ACTION, value="爬坡", start_ms=1000, end_ms=3000,
                statement=statement("action", "爬坡"),
            ),
            ObjectiveFact(
                layer=ObjectiveFactLayer.SCENE, value="山路", start_ms=1000, end_ms=3000,
                statement=statement("scene", "山路"),
            ),
        ],
    )

    events = build_timeline_events(segment, annotation)

    assert len(events) == 1
    assert events[0].subject_name == "泰钽700"
    assert events[0].action == "爬坡"
    assert events[0].scene == "山路"
    assert events[0].entity_id == f"{segment.id}:car_1"


def test_same_local_entity_name_across_segments_is_only_probable():
    video_id = uuid4()
    first = VideoTimelineEvent(
        video_id=video_id, start_ms=0, end_ms=1000,
        subject_name="泰钽700", entity_id="segment-a:car_1", action="行驶",
        time_basis="observed_interval",
    )
    second = VideoTimelineEvent(
        video_id=video_id, start_ms=1000, end_ms=2000,
        subject_name="泰钽700", entity_id="segment-b:car_1", action="爬坡",
        time_basis="observed_interval",
    )

    windows = build_sequence_windows([first, second])

    assert len(windows) == 1
    assert windows[0].continuity_status == "probable_continuity"


def test_source_cut_prevents_sequence_window_join():
    video_id = uuid4()
    events = [
        VideoTimelineEvent(
            video_id=video_id, start_ms=0, end_ms=1000,
            subject_name="泰钽700", entity_id="segment-a:car_1", action="行驶",
            time_basis="observed_interval",
        ),
        VideoTimelineEvent(
            video_id=video_id, start_ms=1000, end_ms=2000,
            subject_name="泰钽700", entity_id="segment-b:car_1", action="爬坡",
            time_basis="observed_interval",
        ),
    ]

    windows = build_sequence_windows(events, source_cut_boundaries=[1000])

    assert len(windows) == 2


def test_stable_entity_track_and_observed_motion_confirm_continuity():
    video_id = uuid4()
    events = [
        VideoTimelineEvent(
            video_id=video_id,
            start_ms=0,
            end_ms=1000,
            subject_name="泰钽700",
            entity_id="segment-a:car_1",
            entity_track_id=f"{video_id}:car_1",
            action="行驶",
            continuous_motion=True,
            time_basis="observed_interval",
            frame_ids=["frame_0", "frame_1"],
        ),
        VideoTimelineEvent(
            video_id=video_id,
            start_ms=1000,
            end_ms=2000,
            subject_name="泰钽700",
            entity_id="segment-b:car_1",
            entity_track_id=f"{video_id}:car_1",
            action="爬坡",
            continuous_motion=True,
            time_basis="observed_interval",
            frame_ids=["frame_2", "frame_3"],
        ),
    ]

    windows = build_sequence_windows(events)

    assert len(windows) == 1
    assert windows[0].continuity_status == "confirmed_continuity"
    assert events[1].same_entity_as_previous is True


def test_long_same_subject_stage_sequence_is_not_split_by_ocr_changes():
    """A 40s speech stays one semantic sequence; OCR changes are sub-events."""
    video_id = uuid4()
    events = [
        VideoTimelineEvent(
            video_id=video_id, start_ms=5000, end_ms=20_000,
            subject_name="男性嘉宾", action="演讲", scene="发布会舞台",
            ocr=["泰钽700"], time_basis="observed_interval",
        ),
        VideoTimelineEvent(
            video_id=video_id, start_ms=20_000, end_ms=32_000,
            subject_name="男性嘉宾", action="演讲", scene="发布会舞台",
            ocr=["全地形豪华电驱越野"], time_basis="observed_interval",
        ),
        VideoTimelineEvent(
            video_id=video_id, start_ms=32_000, end_ms=45_000,
            subject_name="男性嘉宾", action="演讲", scene="发布会舞台",
            ocr=["核心参数"], time_basis="observed_interval",
        ),
    ]

    windows = build_sequence_windows(events)

    assert len(windows) == 1
    assert windows[0].start_ms == 5000
    assert windows[0].end_ms == 45_000
    assert "男性嘉宾" in windows[0].ordered_summary
    assert "演讲" in windows[0].ordered_summary


def test_subject_change_breaks_long_stage_sequence():
    video_id = uuid4()
    events = [
        VideoTimelineEvent(
            video_id=video_id, start_ms=5000, end_ms=45_000,
            subject_name="男性嘉宾", action="演讲", scene="发布会舞台",
            time_basis="observed_interval",
        ),
        VideoTimelineEvent(
            video_id=video_id, start_ms=46_000, end_ms=71_000,
            subject_name="女主持人", action="主持", scene="发布会舞台",
            time_basis="observed_interval",
        ),
    ]

    windows = build_sequence_windows(events)

    assert len(windows) == 2
    assert windows[0].end_ms == 45_000
    assert windows[1].start_ms == 46_000

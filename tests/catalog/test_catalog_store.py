from pathlib import Path
from uuid import uuid4

from clipatlas.catalog.store import CatalogStore
from clipatlas.domain.models import (
    AnnotationOrigin,
    ObjectiveFact,
    ObjectiveFactLayer,
    SegmentSource,
    SemanticAnnotation,
    VideoAsset,
    VideoSegment,
)
from clipatlas.video.models import IngestedVideo, MediaMetadata


def _ingested() -> IngestedVideo:
    video = VideoAsset(
        filename="movie.mp4",
        source_uri="file:///media/movie.mp4",
        duration_ms=10_000,
        width=1920,
        height=1080,
        fps=25.0,
    )
    first = VideoSegment(
        video_id=video.id,
        start_ms=0,
        end_ms=4_000,
        source=SegmentSource.SCENE_DETECTION,
    )
    second = VideoSegment(
        video_id=video.id,
        start_ms=4_000,
        end_ms=10_000,
        source=SegmentSource.SCENE_DETECTION,
    )
    return IngestedVideo(
        video=video,
        metadata=MediaMetadata(
            duration_ms=10_000,
            width=1920,
            height=1080,
            fps=25.0,
            video_codec="h264",
            has_audio=True,
        ),
        segments=[first, second],
        frames_by_segment={
            first.id: ["file:///cache/a.jpg", "file:///cache/b.jpg"],
            second.id: ["file:///cache/c.jpg"],
        },
    )


def test_catalog_persists_prepared_video_segments_and_frames_across_reopen(tmp_path: Path) -> None:
    db_path = tmp_path / "clipatlas.sqlite3"
    prepared = _ingested()
    CatalogStore(db_path).save_prepared_video(prepared)

    loaded = CatalogStore(db_path).get_ingested_video(prepared.video.id)

    assert loaded is not None
    assert loaded.video == prepared.video
    assert loaded.metadata == prepared.metadata
    assert loaded.segments == prepared.segments
    assert loaded.frames_by_segment == prepared.frames_by_segment


def test_existing_scene_listing_can_read_only_the_overlapping_time_window(tmp_path):
    store = CatalogStore(tmp_path / "catalog.sqlite3")
    prepared = _ingested()
    store.save_prepared_video(prepared)
    assert store.list_segments(prepared.video.id, limit=10, offset=0) == prepared.segments
    assert store.list_segments(prepared.video.id, limit=10, offset=0,
                               start_ms=4000, end_ms=5000) == [prepared.segments[1]]
    assert store.list_segments(prepared.video.id, limit=10, offset=0,
                               start_ms=3000, end_ms=4000) == [prepared.segments[0]]


def test_catalog_keeps_ai_and_human_annotations_as_separate_revisions(tmp_path: Path) -> None:
    store = CatalogStore(tmp_path / "clipatlas.sqlite3")
    prepared = _ingested()
    store.save_prepared_video(prepared)
    segment_id = prepared.segments[0].id
    ai = SemanticAnnotation(
        segment_id=segment_id,
        origin=AnnotationOrigin.AI,
        provider="qwen",
        model="qwen3.7-flash",
        description="A man walks alone in rain",
        actions=["walking"],
        scene=["rainy street"],
        confidence=0.9,
    )
    human = SemanticAnnotation(
        id=uuid4(),
        segment_id=segment_id,
        origin=AnnotationOrigin.HUMAN,
        description="一个男人独自在雨夜街道行走",
        actions=["独自行走"],
        scene=["城市雨夜"],
        verified=True,
        revision=2,
    )

    store.save_annotation(ai)
    store.save_annotation(human)

    annotations = store.list_annotations(segment_id)
    assert [annotation.id for annotation in annotations] == [ai.id, human.id]
    assert annotations[0].description == "A man walks alone in rain"
    assert annotations[1].description == "一个男人独自在雨夜街道行走"
    assert store.has_ai_annotation(segment_id, provider="qwen") is True
    assert store.has_ai_annotation(segment_id, provider="other") is False


def test_video_segment_page_and_effective_annotation_stats(tmp_path: Path) -> None:
    store = CatalogStore(tmp_path / "clipatlas.sqlite3")
    video = VideoAsset(
        filename="three.mp4",
        source_uri="file:///media/three.mp4",
        duration_ms=9_000,
        width=1920,
        height=1080,
        fps=25.0,
    )
    segments = [
        VideoSegment(
            video_id=video.id,
            start_ms=index * 3_000,
            end_ms=(index + 1) * 3_000,
            source=SegmentSource.SCENE_DETECTION,
        )
        for index in range(3)
    ]
    store.save_prepared_video(
        IngestedVideo(
            video=video,
            metadata=MediaMetadata(
                duration_ms=9_000,
                width=1920,
                height=1080,
                fps=25.0,
                video_codec="h264",
                has_audio=True,
            ),
            segments=segments,
            frames_by_segment={segment.id: [] for segment in segments},
        )
    )
    store.save_annotation(
        SemanticAnnotation(
            segment_id=segments[0].id,
            origin=AnnotationOrigin.AI,
            provider="qwen",
            model="qwen3.7-flash",
            description="AI first",
        )
    )
    store.save_annotation(
        SemanticAnnotation(
            segment_id=segments[1].id,
            origin=AnnotationOrigin.AI,
            provider="qwen",
            model="qwen3.7-flash",
            description="AI second",
        )
    )
    store.save_annotation(
        SemanticAnnotation(
            segment_id=segments[1].id,
            origin=AnnotationOrigin.HUMAN,
            description="人工第二段",
            verified=True,
            locked=True,
            revision=2,
        )
    )

    assert store.count_segments(video.id) == 3
    assert store.list_segments(video.id, limit=2, offset=1) == segments[1:]

    stats = store.get_video_annotation_stats(video.id)
    assert stats.segments_total == 3
    assert stats.annotated == 2
    assert stats.ai_effective == 1
    assert stats.human_effective == 1
    assert stats.locked == 1


def test_keyword_search_is_scoped_to_selected_videos_and_effective_revision(tmp_path: Path) -> None:
    store = CatalogStore(tmp_path / "clipatlas.sqlite3")
    selected = _ingested()
    outside = _ingested()
    store.save_prepared_video(selected)
    store.save_prepared_video(outside)

    selected_segment = selected.segments[0].id
    outside_segment = outside.segments[0].id
    store.save_annotation(SemanticAnnotation(
        segment_id=selected_segment, origin=AnnotationOrigin.AI,
        description="旧标注含大梁", objects=["大梁"], revision=1,
    ))
    store.save_annotation(SemanticAnnotation(
        segment_id=selected_segment, origin=AnnotationOrigin.HUMAN,
        description="当前人工标注是座椅", objects=["座椅"], revision=2,
    ))
    store.save_annotation(SemanticAnnotation(
        segment_id=outside_segment, origin=AnnotationOrigin.AI,
        description="大梁承受扭转", objects=["大梁"], actions=["承受扭转"],
    ))

    hits = store.search_annotations_by_keywords(
        ["大梁", "扭转"], video_ids=[selected.video.id], limit=12,
    )

    assert hits == []


def test_fourteen_layer_objective_facts_persist_and_are_locally_searchable(tmp_path: Path) -> None:
    db_path = tmp_path / "clipatlas.sqlite3"
    prepared = _ingested()
    store = CatalogStore(db_path)
    store.save_prepared_video(prepared)
    annotation = SemanticAnnotation(
        segment_id=prepared.segments[0].id,
        origin=AnnotationOrigin.AI,
        description="车辆底盘画面",
        facts=[ObjectiveFact(
            layer=ObjectiveFactLayer.SPATIAL_RELATION,
            value="后桥位于大梁下方",
            evidence="frame:2",
            confidence=0.91,
        )],
    )
    store.save_annotation(annotation)

    reopened = CatalogStore(db_path)
    loaded = reopened.get_effective_annotation(annotation.segment_id)
    hits = reopened.search_annotations_by_keywords(["后桥位于大梁下方"])

    assert loaded is not None and loaded.facts == annotation.facts
    assert [segment_id for segment_id, _ in hits] == [annotation.segment_id]


def test_contamination_without_segment_id_is_found_by_video_time_overlap(tmp_path: Path) -> None:
    prepared = _ingested()
    store = CatalogStore(tmp_path / "clipatlas.sqlite3")
    store.save_prepared_video(prepared)
    with store._connect() as connection:
        connection.execute(
            "INSERT INTO catalog_contamination_ranges "
            "(id,video_id,segment_id,start_ms,end_ms,kind,source,created_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (str(uuid4()), str(prepared.video.id), None, 1000, 2000, "black_title",
             "test", prepared.video.created_at.isoformat()),
        )
    assert store.get_segment_contamination_kinds(prepared.segments[0].id) == ["black_title"]
    assert store.get_segment_contamination_kinds(prepared.segments[1].id) == []

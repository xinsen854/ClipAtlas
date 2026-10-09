from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from clipatlas.catalog.store import CatalogStore
from clipatlas.domain.models import (
    AnnotationOrigin,
    SegmentSource,
    SemanticAnnotation,
    VideoAsset,
    VideoSegment,
)
from clipatlas.main import create_app
from clipatlas.video.models import IngestedVideo, MediaMetadata


def _client_with_video(tmp_path: Path) -> tuple[TestClient, VideoAsset, list[VideoSegment]]:
    catalog = CatalogStore(tmp_path / "catalog.sqlite3")
    video = VideoAsset(
        filename="movie.mp4",
        source_uri="file:///media/movie.mp4",
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
    catalog.save_prepared_video(
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
    catalog.save_annotation(
        SemanticAnnotation(
            segment_id=segments[0].id,
            origin=AnnotationOrigin.AI,
            provider="qwen",
            model="qwen3.7-flash",
            description="AI 第一段",
        )
    )
    catalog.save_annotation(
        SemanticAnnotation(
            segment_id=segments[1].id,
            origin=AnnotationOrigin.AI,
            provider="qwen",
            model="qwen3.7-flash",
            description="旧 AI 第二段",
        )
    )
    catalog.save_annotation(
        SemanticAnnotation(
            segment_id=segments[1].id,
            origin=AnnotationOrigin.HUMAN,
            description="人工第二段",
            verified=True,
            locked=True,
            revision=2,
        )
    )

    app = create_app()
    app.state.library_catalog = catalog
    return TestClient(app), video, segments


def test_video_detail_returns_metadata_and_effective_annotation_stats(tmp_path: Path) -> None:
    client, video, _segments = _client_with_video(tmp_path)

    response = client.get(f"/api/v1/videos/{video.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["video"]["id"] == str(video.id)
    assert body["video"]["duration_ms"] == 9_000
    assert body["video"]["width"] == 1920
    assert body["video"]["height"] == 1080
    assert body["video"]["fps"] == 25.0
    assert body["segment_count"] == 3
    assert body["annotation_stats"] == {
        "segments_total": 3,
        "annotated": 2,
        "ai_effective": 1,
        "human_effective": 1,
        "locked": 1,
    }


def test_video_segments_are_paginated_and_use_effective_annotation(tmp_path: Path) -> None:
    client, video, segments = _client_with_video(tmp_path)

    response = client.get(
        f"/api/v1/videos/{video.id}/segments",
        params={"limit": 2, "offset": 1},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["limit"] == 2
    assert body["offset"] == 1
    assert [item["segment"]["id"] for item in body["items"]] == [
        str(segments[1].id),
        str(segments[2].id),
    ]
    assert body["items"][0]["annotation"]["origin"] == "human"
    assert body["items"][0]["annotation"]["description"] == "人工第二段"
    assert body["items"][0]["annotation"]["revision"] == 2
    assert body["items"][1]["annotation"] is None


def test_video_endpoints_validate_not_found_and_pagination(tmp_path: Path) -> None:
    client, _video, _segments = _client_with_video(tmp_path)
    missing = uuid4()

    assert client.get(f"/api/v1/videos/{missing}").status_code == 404
    assert client.get(f"/api/v1/videos/{missing}/segments").status_code == 404
    assert (
        client.get(
            f"/api/v1/videos/{missing}/segments",
            params={"limit": 0},
        ).status_code
        == 422
    )
    assert (
        client.get(
            f"/api/v1/videos/{missing}/segments",
            params={"limit": 201},
        ).status_code
        == 422
    )
    assert (
        client.get(
            f"/api/v1/videos/{missing}/segments",
            params={"offset": -1},
        ).status_code
        == 422
    )

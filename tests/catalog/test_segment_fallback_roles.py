from pathlib import Path
from uuid import uuid4

import pytest

from clipatlas.catalog.segment_roles import SegmentFallbackRoleStore
from clipatlas.catalog.store import CatalogStore
from clipatlas.domain.models import SegmentSource


def _catalog_with_segment(tmp_path: Path):
    catalog = CatalogStore(tmp_path / "library.sqlite3")
    video_id = uuid4()
    segment_id = uuid4()
    with catalog._connect() as connection:
        connection.execute(
            "INSERT INTO catalog_videos (id,filename,source_uri,duration_ms,width,height,fps,video_codec,has_audio,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (str(video_id), "a.mp4", "file:///a.mp4", 10000, 1920, 1080, 25.0, "h264", 0,
             "2026-01-01T00:00:00+00:00"),
        )
        connection.execute(
            "INSERT INTO catalog_segments (id,video_id,start_ms,end_ms,source,created_at) VALUES (?,?,?,?,?,?)",
            (str(segment_id), str(video_id), 1000, 9000, SegmentSource.AI.value,
             "2026-01-01T00:00:00+00:00"),
        )
    return catalog, video_id, segment_id


def test_segment_can_be_marked_generic_without_marking_whole_video(tmp_path: Path):
    catalog, video_id, segment_id = _catalog_with_segment(tmp_path)
    roles = SegmentFallbackRoleStore(catalog)

    roles.set_role(segment_id, "generic")

    assert roles.get_role(segment_id) == "generic"
    assert roles.list_segments("generic", video_ids=[video_id]) == [segment_id]
    assert catalog.get_video(video_id).fallback_role == "normal"


def test_segment_can_be_reserved_as_explicit_review_placeholder(tmp_path: Path):
    catalog, video_id, segment_id = _catalog_with_segment(tmp_path)
    roles = SegmentFallbackRoleStore(catalog)

    roles.set_role(segment_id, "review_placeholder")

    assert roles.get_role(segment_id) == "review_placeholder"
    assert roles.list_segments("review_placeholder", video_ids=[video_id]) == [segment_id]


def test_normal_role_removes_sparse_override(tmp_path: Path):
    catalog, _, segment_id = _catalog_with_segment(tmp_path)
    roles = SegmentFallbackRoleStore(catalog)
    roles.set_role(segment_id, "generic")
    roles.set_role(segment_id, "normal")
    assert roles.get_role(segment_id) == "normal"
    assert roles.list_segments("generic") == []


def test_unknown_segment_cannot_be_marked(tmp_path: Path):
    catalog = CatalogStore(tmp_path / "library.sqlite3")
    roles = SegmentFallbackRoleStore(catalog)
    with pytest.raises(KeyError):
        roles.set_role(uuid4(), "generic")

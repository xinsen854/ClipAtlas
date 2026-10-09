"""1.0.7 catalog 视频按项目隔离检索范围。"""
from pathlib import Path
from uuid import uuid4

from clipatlas.catalog.store import CatalogStore
from clipatlas.domain.models import SegmentSource, VideoAsset, VideoSegment
from clipatlas.video.models import IngestedVideo, MediaMetadata


def _ingested(name: str) -> IngestedVideo:
    video = VideoAsset(
        filename=name,
        source_uri=f"file:///media/{name}",
        duration_ms=8_000,
        width=1920,
        height=1080,
        fps=25.0,
    )
    seg = VideoSegment(
        video_id=video.id,
        start_ms=0,
        end_ms=8_000,
        source=SegmentSource.SCENE_DETECTION,
    )
    return IngestedVideo(
        video=video,
        metadata=MediaMetadata(
            duration_ms=8_000, width=1920, height=1080, fps=25.0,
            video_codec="h264", has_audio=True,
        ),
        segments=[seg],
        frames_by_segment={seg.id: []},
    )


def test_project_video_scope_excludes_other_projects_and_unassigned_legacy(tmp_path: Path) -> None:
    store = CatalogStore(tmp_path / "catalog.sqlite3")
    pa, pb = uuid4(), uuid4()
    vid_a = _ingested("a.mp4")
    vid_b = _ingested("b.mp4")
    vid_legacy = _ingested("old.mp4")

    store.save_prepared_video(vid_a, project_id=pa)
    store.save_prepared_video(vid_b, project_id=pb)
    store.save_prepared_video(vid_legacy)  # 遗留，project_id 为空

    scope_a = set(store.list_video_ids_for_project(pa))
    scope_b = set(store.list_video_ids_for_project(pb))
    all_ids = set(store.list_video_ids(limit=1000))

    assert scope_a == {vid_a.video.id}
    assert vid_b.video.id not in scope_a
    assert scope_b == {vid_b.video.id}
    assert all_ids == {vid_a.video.id, vid_b.video.id, vid_legacy.video.id}


def test_existing_project_binding_is_not_overwritten(tmp_path: Path) -> None:
    store = CatalogStore(tmp_path / "catalog.sqlite3")
    pa, pb = uuid4(), uuid4()
    prepared = _ingested("a.mp4")
    store.save_prepared_video(prepared, project_id=pa)
    # 再次以另一项目保存同一视频，已有归属不应被覆盖（COALESCE）。
    store.save_prepared_video(prepared, project_id=pb)
    scope_pb = set(store.list_video_ids_for_project(pb))
    assert prepared.video.id not in scope_pb
    assert prepared.video.id in set(store.list_video_ids_for_project(pa))

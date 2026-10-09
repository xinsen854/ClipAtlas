"""素材库按项目严格隔离，升级前 NULL 数据只在迁移时分配一次。"""
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from clipatlas.catalog.store import CatalogStore
from clipatlas.domain.models import SegmentSource, VideoAsset, VideoSegment
from clipatlas.library.store import LibraryStore
from clipatlas.projects.models import Project
from clipatlas.video.models import IngestedVideo, MediaMetadata


def _setup(tmp_path: Path):
    store = LibraryStore(tmp_path / "library.sqlite3")
    pa, pb = uuid4(), uuid4()
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_legacy = tmp_path / "legacy"
    for d in (dir_a, dir_b, dir_legacy):
        d.mkdir()
    root_a = store.add_root(dir_a, project_id=pa)
    root_b = store.add_root(dir_b, project_id=pb)
    root_legacy = store.add_root(dir_legacy)  # 升级前遗留，project_id 为空
    store.save_observation(root_a.id, dir_a / "a.mp4", 1, 1, "fp-a")
    store.save_observation(root_b.id, dir_b / "b.mp4", 1, 1, "fp-b")
    store.save_observation(root_legacy.id, dir_legacy / "old.mp4", 1, 1, "fp-old")
    return store, pa, pb, root_a, root_b, root_legacy


def _names(items) -> set[str]:
    return {Path(i.source_path).name for i in items}


def test_roots_are_strictly_isolated_and_legacy_is_not_visible_to_projects(tmp_path: Path) -> None:
    store, pa, pb, root_a, root_b, root_legacy = _setup(tmp_path)

    roots_a = {r.id for r in store.list_roots(project_id=pa)}
    roots_b = {r.id for r in store.list_roots(project_id=pb)}
    all_roots = {r.id for r in store.list_roots()}

    assert roots_a == {root_a.id}
    assert root_b.id not in roots_a
    assert roots_b == {root_b.id}
    assert all_roots == {root_a.id, root_b.id, root_legacy.id}


def test_items_are_isolated_by_project(tmp_path: Path) -> None:
    store, pa, pb, *_ = _setup(tmp_path)
    names_a = _names(store.list_items(project_id=pa, limit=100, offset=0))
    names_b = _names(store.list_items(project_id=pb, limit=100, offset=0))
    assert names_a == {"a.mp4"}
    assert names_b == {"b.mp4"}


def test_counts_are_isolated_by_project(tmp_path: Path) -> None:
    store, pa, pb, *_ = _setup(tmp_path)
    assert sum(store.counts_by_status(project_id=pa).values()) == 1
    assert sum(store.counts_by_status(project_id=pb).values()) == 1
    assert sum(store.counts_by_status().values()) == 3


def test_re_adding_legacy_root_under_project_backfills_owner(tmp_path: Path) -> None:
    store = LibraryStore(tmp_path / "library.sqlite3")
    pa = uuid4()
    folder = tmp_path / "media"
    folder.mkdir()
    legacy = store.add_root(folder)
    assert legacy.project_id is None
    backfilled = store.add_root(folder, project_id=pa)
    assert backfilled.project_id == pa


def _prepared(path: Path) -> IngestedVideo:
    video = VideoAsset(
        filename=path.name, source_uri=path.as_uri(), duration_ms=8000,
        width=1920, height=1080, fps=25.0,
    )
    segment = VideoSegment(
        video_id=video.id, start_ms=0, end_ms=8000,
        source=SegmentSource.SCENE_DETECTION,
    )
    return IngestedVideo(
        video=video,
        metadata=MediaMetadata(
            duration_ms=8000, width=1920, height=1080, fps=25.0,
            video_codec="h264", has_audio=True,
        ),
        segments=[segment], frames_by_segment={segment.id: []},
    )


def test_startup_does_not_guess_legacy_root_ownership_from_creation_times(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "library.sqlite3"
    store = LibraryStore(db_path)
    catalog = CatalogStore(db_path)
    first_dir, second_dir = tmp_path / "first", tmp_path / "second"
    first_dir.mkdir(); second_dir.mkdir()
    first_root = store.add_root(first_dir)
    second_root = store.add_root(second_dir)
    first_media, second_media = first_dir / "a.mp4", second_dir / "b.mp4"
    store.save_observation(first_root.id, first_media, 1, 1, "a")
    store.save_observation(second_root.id, second_media, 1, 1, "b")
    first_item = store.get_item_by_path(first_media)
    second_item = store.get_item_by_path(second_media)
    assert first_item is not None and second_item is not None
    first_video, second_video = _prepared(first_media), _prepared(second_media)
    catalog.save_prepared_video(first_video)
    catalog.save_prepared_video(second_video)
    store.complete(first_item.id, first_video.video.id)
    store.complete(second_item.id, second_video.video.id)

    first_time = datetime(2026, 9, 8, 2, 37, tzinfo=UTC)
    second_time = datetime(2026, 9, 9, 2, 4, tzinfo=UTC)
    with store._connect() as connection:
        connection.execute(
            "UPDATE library_roots SET created_at=? WHERE id=?",
            (first_time.isoformat(), str(first_root.id)),
        )
        connection.execute(
            "UPDATE library_roots SET created_at=? WHERE id=?",
            (second_time.isoformat(), str(second_root.id)),
        )
    project_a = Project(name="200W", created_at=first_time - timedelta(minutes=7))
    project_b = Project(name="0909", created_at=second_time + timedelta(hours=1))

    assert store.migrate_legacy_project_ownership([project_a, project_b]) == 0
    assert store.migrate_legacy_project_ownership([project_a, project_b]) == 0
    assert store.list_roots(project_id=project_a.id) == []
    assert store.list_roots(project_id=project_b.id) == []
    assert catalog.list_video_ids_for_project(project_a.id) == []
    assert catalog.list_video_ids_for_project(project_b.id) == []
    assert store.get_root(first_root.id).project_id is None
    assert store.get_root(second_root.id).project_id is None

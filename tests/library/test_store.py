from pathlib import Path
from uuid import uuid4

from clipatlas.library.models import LibraryItemStatus
from clipatlas.library.store import LibraryStore


def _observed(store: LibraryStore, root_id, path: Path, fingerprint: str = "fp1"):
    return store.save_observation(
        root_id=root_id,
        source_path=path,
        size_bytes=100,
        mtime_ns=123,
        fingerprint=fingerprint,
    )


def test_store_persists_root_and_completed_item_across_reopen(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    movie = (media / "movie.mp4").resolve()
    db_path = tmp_path / "library.sqlite3"

    store = LibraryStore(db_path)
    root = store.add_root(media)
    assert store.list_roots()[0].id == root.id
    assert _observed(store, root.id, movie) == "discovered"

    claimed = store.claim_next()
    assert claimed is not None
    assert claimed.status is LibraryItemStatus.PROBING
    assert claimed.attempts == 1

    video_id = uuid4()
    store.complete(claimed.id, video_id)

    reopened = LibraryStore(db_path)
    item = reopened.get_item_by_path(movie)
    assert item is not None
    assert item.status is LibraryItemStatus.COMPLETED
    assert item.video_id == video_id
    assert item.processed_fingerprint == item.fingerprint == "fp1"


def test_changed_observation_requeues_and_clears_previous_processing_state(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    movie = (media / "movie.mp4").resolve()
    store = LibraryStore(tmp_path / "library.sqlite3")
    root = store.add_root(media)
    _observed(store, root.id, movie, "fp1")
    claimed = store.claim_next()
    assert claimed is not None
    store.complete(claimed.id, uuid4())

    outcome = store.save_observation(root.id, movie, 101, 124, "fp2")

    assert outcome == "changed"
    item = store.get_item_by_path(movie)
    assert item is not None
    assert item.status is LibraryItemStatus.QUEUED
    assert item.video_id is None
    assert item.processed_fingerprint is None
    assert item.last_error is None
    assert item.fingerprint == "fp2"
    assert item.size_bytes == 101
    assert item.mtime_ns == 124


def test_unchanged_completed_and_failed_items_keep_their_status(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    completed_path = (media / "completed.mp4").resolve()
    failed_path = (media / "failed.mp4").resolve()
    store = LibraryStore(tmp_path / "library.sqlite3")
    root = store.add_root(media)

    _observed(store, root.id, completed_path, "completed-fp")
    claimed = store.claim_next()
    assert claimed is not None
    store.complete(claimed.id, uuid4())

    _observed(store, root.id, failed_path, "failed-fp")
    claimed = store.claim_next()
    assert claimed is not None
    store.fail(claimed.id, "bad media")

    assert _observed(store, root.id, completed_path, "completed-fp") == "unchanged"
    assert _observed(store, root.id, failed_path, "failed-fp") == "unchanged"
    completed = store.get_item_by_path(completed_path)
    failed = store.get_item_by_path(failed_path)
    assert completed is not None and completed.status is LibraryItemStatus.COMPLETED
    assert failed is not None and failed.status is LibraryItemStatus.FAILED


def test_claim_next_is_oldest_first_and_increments_attempts(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    first = (media / "first.mp4").resolve()
    second = (media / "second.mp4").resolve()
    store = LibraryStore(tmp_path / "library.sqlite3")
    root = store.add_root(media)
    _observed(store, root.id, first, "one")
    _observed(store, root.id, second, "two")

    first_claim = store.claim_next()
    second_claim = store.claim_next()

    assert first_claim is not None and first_claim.source_path == str(first)
    assert first_claim.attempts == 1
    assert second_claim is not None and second_claim.source_path == str(second)
    assert second_claim.attempts == 1
    assert store.claim_next() is None


def test_recover_interrupted_only_requeues_inflight_states(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    store = LibraryStore(tmp_path / "library.sqlite3")
    root = store.add_root(media)
    for index in range(5):
        path = (media / f"movie-{index}.mp4").resolve()
        _observed(store, root.id, path, f"fp-{index}")

    items = store.list_items(root_id=root.id, limit=10)
    store.set_status(items[0].id, LibraryItemStatus.PROBING)
    store.set_status(items[1].id, LibraryItemStatus.SCENE_DETECTION)
    store.set_status(items[2].id, LibraryItemStatus.FRAME_EXTRACTION)
    store.set_status(items[3].id, LibraryItemStatus.FAILED)
    store.set_status(items[4].id, LibraryItemStatus.MISSING)

    assert store.recover_interrupted() == 3

    statuses = {Path(item.source_path).name: item.status for item in store.list_items(limit=10)}
    assert statuses["movie-0.mp4"] is LibraryItemStatus.QUEUED
    assert statuses["movie-1.mp4"] is LibraryItemStatus.QUEUED
    assert statuses["movie-2.mp4"] is LibraryItemStatus.QUEUED
    assert statuses["movie-3.mp4"] is LibraryItemStatus.FAILED
    assert statuses["movie-4.mp4"] is LibraryItemStatus.MISSING


def test_retry_only_failed_and_failure_error_is_bounded(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    failed_path = (media / "failed.mp4").resolve()
    queued_path = (media / "queued.mp4").resolve()
    store = LibraryStore(tmp_path / "library.sqlite3")
    root = store.add_root(media)
    _observed(store, root.id, failed_path, "failed")
    _observed(store, root.id, queued_path, "queued")

    failed = store.claim_next()
    assert failed is not None
    store.fail(failed.id, "x" * 3000)

    failed_item = store.get_item_by_path(failed_path)
    queued_item = store.get_item_by_path(queued_path)
    assert failed_item is not None and len(failed_item.last_error or "") == 2000
    assert queued_item is not None
    assert store.retry(queued_item.id) is False
    assert store.retry(failed_item.id) is True

    retried = store.get_item_by_path(failed_path)
    assert retried is not None
    assert retried.status is LibraryItemStatus.QUEUED
    assert retried.last_error is None


def test_counts_by_status_and_mark_missing(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    store = LibraryStore(tmp_path / "library.sqlite3")
    root = store.add_root(media)
    first = (media / "first.mp4").resolve()
    second = (media / "second.mp4").resolve()
    _observed(store, root.id, first, "one")
    _observed(store, root.id, second, "two")

    second_item = store.get_item_by_path(second)
    assert second_item is not None
    store.mark_missing(second_item.id)

    counts = store.counts_by_status()
    assert counts[LibraryItemStatus.QUEUED] == 1
    assert counts[LibraryItemStatus.MISSING] == 1


def test_get_item_returns_item_by_id_and_none_for_unknown_id(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    movie = (media / "movie.mp4").resolve()
    store = LibraryStore(tmp_path / "library.sqlite3")
    root = store.add_root(media)
    _observed(store, root.id, movie)
    item = store.get_item_by_path(movie)
    assert item is not None

    assert store.get_item(item.id) == item
    assert store.get_item(uuid4()) is None

from datetime import UTC
from uuid import uuid4

from clipatlas.library.models import LibraryItem, LibraryItemStatus, LibraryRoot


def test_library_status_contains_persistent_queue_stages() -> None:
    assert {status.value for status in LibraryItemStatus} == {
        "QUEUED",
        "PROBING",
        "SCENE_DETECTION",
        "FRAME_EXTRACTION",
        "COMPLETED",
        "FAILED",
        "MISSING",
    }


def test_library_models_use_clipatlas_owned_identity_and_utc_timestamps() -> None:
    root = LibraryRoot(path="C:/media")
    item = LibraryItem(
        root_id=root.id,
        source_path="C:/media/movie.mp4",
        size_bytes=100,
        mtime_ns=123,
        fingerprint="abc",
    )

    assert root.created_at.tzinfo is UTC
    assert item.created_at.tzinfo is UTC
    assert item.updated_at.tzinfo is UTC
    assert item.status is LibraryItemStatus.QUEUED
    assert item.processed_fingerprint is None
    assert item.video_id is None
    assert item.attempts == 0


def test_library_item_accepts_completed_processing_identity() -> None:
    root_id = uuid4()
    video_id = uuid4()
    item = LibraryItem(
        root_id=root_id,
        source_path="C:/media/movie.mp4",
        size_bytes=100,
        mtime_ns=123,
        fingerprint="abc",
        processed_fingerprint="abc",
        status=LibraryItemStatus.COMPLETED,
        video_id=video_id,
    )

    assert item.root_id == root_id
    assert item.video_id == video_id
    assert item.processed_fingerprint == item.fingerprint

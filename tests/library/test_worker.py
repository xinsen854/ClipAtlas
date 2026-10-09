from pathlib import Path

import pytest

from clipatlas.domain.models import VideoAsset
from clipatlas.library.models import LibraryItemStatus
from clipatlas.library.store import LibraryStore
from clipatlas.library.worker import SequentialLibraryWorker
from clipatlas.video.models import IngestedVideo, MediaMetadata


class RecordingProcessor:
    def __init__(self, fail_names: set[str] | None = None) -> None:
        self.fail_names = fail_names or set()
        self.calls: list[str] = []

    async def prepare(self, item_id, source_path: Path, on_stage):
        self.calls.append(source_path.name)
        on_stage(LibraryItemStatus.PROBING)
        on_stage(LibraryItemStatus.SCENE_DETECTION)
        if source_path.name in self.fail_names:
            raise RuntimeError(f"broken media: {source_path.name}")
        on_stage(LibraryItemStatus.FRAME_EXTRACTION)
        metadata = MediaMetadata(
            duration_ms=1_000,
            width=640,
            height=360,
            fps=25.0,
            video_codec="h264",
            has_audio=False,
        )
        return IngestedVideo(
            video=VideoAsset(
                filename=source_path.name,
                source_uri=source_path.resolve().as_uri(),
                duration_ms=metadata.duration_ms,
                width=metadata.width,
                height=metadata.height,
                fps=metadata.fps,
            ),
            metadata=metadata,
            segments=[],
            frames_by_segment={},
        )


def _queue(store: LibraryStore, root_id, path: Path, fingerprint: str) -> None:
    path.write_bytes(fingerprint.encode())
    stat = path.stat()
    store.save_observation(
        root_id=root_id,
        source_path=path,
        size_bytes=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        fingerprint=fingerprint,
    )


@pytest.mark.asyncio
async def test_worker_processes_exactly_one_item_per_run_once(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    store = LibraryStore(tmp_path / "library.sqlite3")
    root = store.add_root(media)
    first = media / "first.mp4"
    second = media / "second.mp4"
    _queue(store, root.id, first, "one")
    _queue(store, root.id, second, "two")
    processor = RecordingProcessor()
    worker = SequentialLibraryWorker(store=store, processor=processor)

    assert await worker.run_once() is True

    first_item = store.get_item_by_path(first)
    second_item = store.get_item_by_path(second)
    assert first_item is not None
    assert second_item is not None
    assert first_item.status is LibraryItemStatus.COMPLETED
    assert first_item.video_id is not None
    assert first_item.attempts == 1
    assert second_item.status is LibraryItemStatus.QUEUED
    assert processor.calls == ["first.mp4"]

    assert await worker.run_once() is True
    assert processor.calls == ["first.mp4", "second.mp4"]
    second_item = store.get_item_by_path(second)
    assert second_item is not None and second_item.status is LibraryItemStatus.COMPLETED


@pytest.mark.asyncio
async def test_worker_failure_marks_only_failed_item_and_next_run_continues(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    store = LibraryStore(tmp_path / "library.sqlite3")
    root = store.add_root(media)
    broken = media / "broken.mp4"
    good = media / "good.mp4"
    _queue(store, root.id, broken, "broken")
    _queue(store, root.id, good, "good")
    processor = RecordingProcessor(fail_names={"broken.mp4"})
    worker = SequentialLibraryWorker(store=store, processor=processor)

    assert await worker.run_once() is True
    broken_item = store.get_item_by_path(broken)
    good_item = store.get_item_by_path(good)
    assert broken_item is not None
    assert good_item is not None
    assert broken_item.status is LibraryItemStatus.FAILED
    assert "broken media" in (broken_item.last_error or "")
    assert good_item.status is LibraryItemStatus.QUEUED

    assert await worker.run_once() is True
    good_item = store.get_item_by_path(good)
    assert good_item is not None and good_item.status is LibraryItemStatus.COMPLETED
    assert processor.calls == ["broken.mp4", "good.mp4"]


@pytest.mark.asyncio
async def test_worker_returns_false_when_queue_is_empty(tmp_path: Path) -> None:
    store = LibraryStore(tmp_path / "library.sqlite3")
    worker = SequentialLibraryWorker(store=store, processor=RecordingProcessor())

    assert await worker.run_once() is False

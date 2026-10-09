import asyncio
from pathlib import Path

import pytest

from clipatlas.domain.models import VideoAsset
from clipatlas.library.models import LibraryItemStatus
from clipatlas.library.store import LibraryStore
from clipatlas.library.worker import SequentialLibraryWorker
from clipatlas.video.models import IngestedVideo, MediaMetadata


class RecordingProcessor:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def prepare(self, item_id, source_path: Path, on_stage):
        self.calls.append(source_path.name)
        on_stage(LibraryItemStatus.PROBING)
        on_stage(LibraryItemStatus.SCENE_DETECTION)
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


class BlockingProcessor(RecordingProcessor):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def prepare(self, item_id, source_path: Path, on_stage):
        self.calls.append(source_path.name)
        on_stage(LibraryItemStatus.PROBING)
        self.started.set()
        await self.release.wait()
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
async def test_single_item_parse_targets_requested_queued_item_not_queue_head(
    tmp_path: Path,
) -> None:
    media = tmp_path / "media"
    media.mkdir()
    store = LibraryStore(tmp_path / "library.sqlite3")
    root = store.add_root(media)
    first = media / "first.mp4"
    second = media / "second.mp4"
    _queue(store, root.id, first, "first")
    _queue(store, root.id, second, "second")
    first_item = store.get_item_by_path(first)
    second_item = store.get_item_by_path(second)
    assert first_item is not None
    assert second_item is not None
    processor = RecordingProcessor()
    worker = SequentialLibraryWorker(store=store, processor=processor)

    assert await worker.parse_item(second_item.id) is True

    first_after = store.get_item(first_item.id)
    second_after = store.get_item(second_item.id)
    assert first_after is not None
    assert second_after is not None
    assert first_after.status is LibraryItemStatus.QUEUED
    assert second_after.status is LibraryItemStatus.COMPLETED
    assert second_after.attempts == 1
    assert processor.calls == ["second.mp4"]


@pytest.mark.asyncio
async def test_single_item_parse_rejects_second_start_while_same_item_is_inflight(
    tmp_path: Path,
) -> None:
    media = tmp_path / "media"
    media.mkdir()
    store = LibraryStore(tmp_path / "library.sqlite3")
    root = store.add_root(media)
    movie = media / "movie.mp4"
    _queue(store, root.id, movie, "movie")
    item = store.get_item_by_path(movie)
    assert item is not None
    processor = BlockingProcessor()
    worker = SequentialLibraryWorker(store=store, processor=processor)

    first = asyncio.create_task(worker.parse_item(item.id))
    await processor.started.wait()

    assert await worker.parse_item(item.id) is False
    inflight = store.get_item(item.id)
    assert inflight is not None
    assert inflight.status is LibraryItemStatus.PROBING
    assert inflight.attempts == 1
    assert processor.calls == ["movie.mp4"]

    processor.release.set()
    assert await first is True
    completed = store.get_item(item.id)
    assert completed is not None
    assert completed.status is LibraryItemStatus.COMPLETED
    assert completed.attempts == 1

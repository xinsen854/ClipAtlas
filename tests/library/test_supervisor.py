import asyncio
import time
from pathlib import Path

import pytest

from clipatlas.library.models import LibraryItemStatus, ScanReport
from clipatlas.library.store import LibraryStore
from clipatlas.library.supervisor import LibrarySupervisor


class RecordingScanner:
    def __init__(self, report: ScanReport | None = None, stop: asyncio.Event | None = None) -> None:
        self.report = report or ScanReport()
        self.stop = stop
        self.calls = 0

    def scan_all(self) -> ScanReport:
        self.calls += 1
        if self.stop is not None:
            self.stop.set()
        return self.report


class BlockingScanner:
    def __init__(self, delay_seconds: float = 0.3) -> None:
        self.delay_seconds = delay_seconds
        self.calls = 0

    def scan_all(self) -> ScanReport:
        self.calls += 1
        time.sleep(self.delay_seconds)
        return ScanReport()


class RecordingWorker:
    def __init__(self, results: list[bool]) -> None:
        self.results = list(results)
        self.calls = 0

    async def run_once(self) -> bool:
        self.calls += 1
        return self.results.pop(0) if self.results else False


def _queue(store: LibraryStore, root_id, path: Path) -> None:
    path.write_bytes(b"video")
    stat = path.stat()
    store.save_observation(root_id, path, stat.st_size, stat.st_mtime_ns, path.name)


@pytest.mark.asyncio
async def test_supervisor_recovers_then_scans_and_drains_queue(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    store = LibraryStore(tmp_path / "library.sqlite3")
    root = store.add_root(media)
    movie = media / "movie.mp4"
    _queue(store, root.id, movie)
    item = store.get_item_by_path(movie)
    assert item is not None
    store.set_status(item.id, LibraryItemStatus.SCENE_DETECTION)

    scanner = RecordingScanner(ScanReport(discovered=2, unchanged=3))
    worker = RecordingWorker([True, True, False])
    supervisor = LibrarySupervisor(store=store, scanner=scanner, worker=worker)

    assert supervisor.recover_interrupted() == 1
    recovered = store.get_item_by_path(movie)
    assert recovered is not None and recovered.status is LibraryItemStatus.QUEUED

    report = await supervisor.run_cycle()

    assert scanner.calls == 1
    assert worker.calls == 3
    assert report.scan.discovered == 2
    assert report.scan.unchanged == 3
    assert report.processed == 2


@pytest.mark.asyncio
async def test_run_cycle_keeps_event_loop_responsive_during_scan(tmp_path: Path) -> None:
    scanner = BlockingScanner()
    worker = RecordingWorker([False])
    supervisor = LibrarySupervisor(
        store=LibraryStore(tmp_path / "library.sqlite3"),
        scanner=scanner,
        worker=worker,
    )

    loop = asyncio.get_running_loop()
    started = loop.time()
    cycle_task = asyncio.create_task(supervisor.run_cycle())

    await asyncio.sleep(0.02)
    elapsed = loop.time() - started

    assert elapsed < 0.15
    await cycle_task
    assert scanner.calls == 1


@pytest.mark.asyncio
async def test_run_forever_stops_cleanly_after_stop_event_is_set(tmp_path: Path) -> None:
    stop = asyncio.Event()
    scanner = RecordingScanner(stop=stop)
    worker = RecordingWorker([False])
    supervisor = LibrarySupervisor(
        store=LibraryStore(tmp_path / "library.sqlite3"),
        scanner=scanner,
        worker=worker,
        interval_seconds=60.0,
    )

    await supervisor.run_forever(stop)

    assert scanner.calls == 1
    assert worker.calls == 1

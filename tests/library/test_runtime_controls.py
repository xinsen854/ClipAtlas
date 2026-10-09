import asyncio
from collections.abc import Callable

import pytest

from clipatlas.app_state import build_provider_registry
from clipatlas.library.models import ScanReport
from clipatlas.library.store import LibraryStore
from clipatlas.library.supervisor import LibrarySupervisor


class RecordingScanner:
    def __init__(self) -> None:
        self.calls = 0

    def scan_all(self) -> ScanReport:
        self.calls += 1
        return ScanReport(discovered=1)


class RecordingWorker:
    def __init__(self, results: list[bool]) -> None:
        self.results = list(results)
        self.calls = 0
        self.after_first: Callable[[], None] | None = None

    async def run_once(self) -> bool:
        self.calls += 1
        result = self.results.pop(0) if self.results else False
        if self.calls == 1 and self.after_first is not None:
            self.after_first()
        await asyncio.sleep(0)
        return result


def _provider_names() -> set[str]:
    return {descriptor.name for descriptor in build_provider_registry().list_descriptors()}


def test_fake_video_provider_is_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("CLIPATLAS_ENABLE_FAKE_PROVIDER", raising=False)
    monkeypatch.delenv("CLIPATLAS_QWEN_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    assert _provider_names() == set()


def test_fake_video_provider_can_still_be_enabled_explicitly(monkeypatch) -> None:
    monkeypatch.setenv("CLIPATLAS_ENABLE_FAKE_PROVIDER", "true")
    monkeypatch.delenv("CLIPATLAS_QWEN_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    assert _provider_names() == {"fake"}


@pytest.mark.asyncio
async def test_supervisor_without_real_processing_provider_scans_but_does_not_consume_queue(
    tmp_path,
) -> None:
    scanner = RecordingScanner()
    worker = RecordingWorker([True, False])
    supervisor = LibrarySupervisor(
        store=LibraryStore(tmp_path / "library.sqlite3"),
        scanner=scanner,
        worker=worker,
        processing_enabled=False,
    )

    report = await supervisor.run_cycle()

    assert scanner.calls == 1
    assert worker.calls == 0
    assert report.processed == 0
    assert supervisor.processing_available is False
    assert supervisor.paused is True
    assert supervisor.resume() is False


@pytest.mark.asyncio
async def test_pause_finishes_current_item_then_stops_before_claiming_the_next(tmp_path) -> None:
    scanner = RecordingScanner()
    worker = RecordingWorker([True, True, False])
    supervisor = LibrarySupervisor(
        store=LibraryStore(tmp_path / "library.sqlite3"),
        scanner=scanner,
        worker=worker,
        processing_enabled=True,
    )
    worker.after_first = supervisor.pause

    report = await supervisor.run_cycle()

    assert report.processed == 1
    assert worker.calls == 1
    assert supervisor.paused is True

    assert supervisor.resume() is True
    resumed = await supervisor.run_cycle()
    assert resumed.processed == 1
    assert worker.calls == 3
    assert supervisor.paused is False

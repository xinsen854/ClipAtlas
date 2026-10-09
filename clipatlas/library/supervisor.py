import asyncio
from dataclasses import dataclass
from typing import Protocol

from clipatlas.library.models import ScanReport
from clipatlas.library.store import LibraryStore


class LibraryScannerLike(Protocol):
    def scan_all(self) -> ScanReport: ...


class LibraryWorkerLike(Protocol):
    async def run_once(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class SupervisorCycleReport:
    scan: ScanReport
    processed: int


class LibrarySupervisor:
    def __init__(
        self,
        store: LibraryStore,
        scanner: LibraryScannerLike,
        worker: LibraryWorkerLike,
        interval_seconds: float = 60.0,
        processing_enabled: bool = True,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self._store = store
        self._scanner = scanner
        self._worker = worker
        self._interval_seconds = interval_seconds
        self._processing_enabled = processing_enabled
        self._paused = False

    @property
    def processing_available(self) -> bool:
        return self._processing_enabled

    @property
    def paused(self) -> bool:
        return self._paused or not self._processing_enabled

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> bool:
        if not self._processing_enabled:
            return False
        self._paused = False
        return True

    def recover_interrupted(self) -> int:
        return self._store.recover_interrupted()

    async def run_cycle(self) -> SupervisorCycleReport:
        scan = await asyncio.to_thread(self._scanner.scan_all)
        processed = 0
        while self.processing_available and not self.paused:
            if not await self._worker.run_once():
                break
            processed += 1
        return SupervisorCycleReport(scan=scan, processed=processed)

    async def run_forever(self, stop: asyncio.Event) -> None:
        self.recover_interrupted()
        while not stop.is_set():
            try:
                await self.run_cycle()
            except asyncio.CancelledError:
                raise
            except Exception:
                # A single scanner/worker failure must not permanently strand
                # the remaining QUEUED items. Keep the supervisor alive and
                # let the next cycle retry the isolated item.
                import logging
                logging.getLogger(__name__).exception("library supervisor cycle failed")
            if stop.is_set():
                break
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._interval_seconds)
            except TimeoutError:
                continue

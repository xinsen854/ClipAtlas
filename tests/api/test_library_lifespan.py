import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from clipatlas.library.scanner import LocalFolderScanner
from clipatlas.library.store import LibraryStore
from clipatlas.library.supervisor import LibrarySupervisor
from clipatlas.main import create_app


def test_create_app_builds_local_library_runtime_from_environment(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "state" / "library.sqlite3"
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("CLIPATLAS_LIBRARY_DB", str(db_path))
    monkeypatch.setenv("CLIPATLAS_LIBRARY_CACHE_ROOT", str(cache_root))
    monkeypatch.setenv("CLIPATLAS_LIBRARY_SCAN_INTERVAL_SECONDS", "17.5")

    app = create_app()

    assert isinstance(app.state.library_store, LibraryStore)
    assert isinstance(app.state.library_scanner, LocalFolderScanner)
    assert isinstance(app.state.library_supervisor, LibrarySupervisor)
    assert db_path.is_file()


class RecordingSupervisor:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def pause(self) -> None:
        pass

    async def run_forever(self, stop: asyncio.Event) -> None:
        self.started = True
        await stop.wait()
        self.stopped = True


def test_fastapi_lifespan_starts_and_stops_library_supervisor(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CLIPATLAS_LIBRARY_DB", str(tmp_path / "library.sqlite3"))
    monkeypatch.setenv("CLIPATLAS_LIBRARY_CACHE_ROOT", str(tmp_path / "cache"))
    app = create_app()
    supervisor = RecordingSupervisor()
    app.state.library_supervisor = supervisor

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert supervisor.started is True

    assert supervisor.stopped is True


class RecordingHypitService:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


def test_fastapi_lifespan_auto_starts_hypit_when_enabled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CLIPATLAS_LIBRARY_DB", str(tmp_path / "library.sqlite3"))
    monkeypatch.setenv("CLIPATLAS_LIBRARY_CACHE_ROOT", str(tmp_path / "cache"))
    monkeypatch.setenv("CLIPATLAS_HYPIT_AUTO_START", "1")
    app = create_app()
    hypit = RecordingHypitService()
    app.state.hypit_service = hypit

    with TestClient(app):
        assert hypit.started is True

    assert hypit.stopped is True

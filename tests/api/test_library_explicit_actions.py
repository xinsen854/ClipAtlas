from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from clipatlas.library.models import LibraryItemStatus
from clipatlas.library.store import LibraryStore
from clipatlas.main import create_app


class FakeExplicitWorker:
    def __init__(self, store: LibraryStore) -> None:
        self.store = store
        self.parse_calls: list[UUID] = []
        self.reparse_calls: list[UUID] = []

    async def parse_item(self, item_id: UUID) -> bool:
        self.parse_calls.append(item_id)
        item = self.store.claim_item(item_id)
        if item is None:
            return False
        self.store.complete(item_id, uuid4())
        return True

    async def reparse_item(self, item_id: UUID) -> bool:
        self.reparse_calls.append(item_id)
        item = self.store.claim_item_for_reparse(item_id)
        if item is None:
            return False
        self.store.complete(item_id, item.video_id or uuid4())
        return True


class FakeSupervisor:
    def __init__(self, *, available: bool = True, paused: bool = True) -> None:
        self.processing_available = available
        self.paused = paused

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> bool:
        if not self.processing_available:
            return False
        self.paused = False
        return True


def _client(
    tmp_path: Path,
    *,
    available: bool = True,
    paused: bool = True,
) -> tuple[TestClient, LibraryStore, FakeExplicitWorker, FakeSupervisor]:
    app = create_app()
    store = LibraryStore(tmp_path / "library.sqlite3")
    worker = FakeExplicitWorker(store)
    supervisor = FakeSupervisor(available=available, paused=paused)
    app.state.library_store = store
    app.state.library_worker = worker
    app.state.library_supervisor = supervisor
    return TestClient(app), store, worker, supervisor


def _queue(store: LibraryStore, media: Path, name: str = "movie.mp4"):
    media.mkdir(exist_ok=True)
    movie = media / name
    movie.write_bytes(b"video")
    root = store.add_root(media)
    stat = movie.stat()
    store.save_observation(root.id, movie, stat.st_size, stat.st_mtime_ns, "fp")
    item = store.get_item_by_path(movie)
    assert item is not None
    return item


def test_explicit_parse_runs_one_queued_item_even_when_background_is_paused(
    tmp_path: Path,
) -> None:
    client, store, worker, supervisor = _client(tmp_path, paused=True)
    item = _queue(store, tmp_path / "media")

    response = client.post(f"/api/v1/library/items/{item.id}/parse")

    assert response.status_code == 200
    assert response.json()["id"] == str(item.id)
    assert response.json()["status"] == LibraryItemStatus.COMPLETED.value
    assert worker.parse_calls == [item.id]
    assert supervisor.paused is True


def test_explicit_parse_rejects_unavailable_provider_before_starting_work(
    tmp_path: Path,
) -> None:
    client, store, worker, _supervisor = _client(tmp_path, available=False, paused=True)
    item = _queue(store, tmp_path / "media")

    response = client.post(f"/api/v1/library/items/{item.id}/parse")

    assert response.status_code == 409
    assert response.json()["detail"] == "video understanding provider is not configured"
    assert worker.parse_calls == []
    queued = store.get_item(item.id)
    assert queued is not None
    assert queued.status is LibraryItemStatus.QUEUED


def test_explicit_parse_maps_duplicate_or_ineligible_start_to_conflict(tmp_path: Path) -> None:
    client, store, worker, _supervisor = _client(tmp_path)
    item = _queue(store, tmp_path / "media")
    first = client.post(f"/api/v1/library/items/{item.id}/parse")
    assert first.status_code == 200

    second = client.post(f"/api/v1/library/items/{item.id}/parse")

    assert second.status_code == 409
    assert worker.parse_calls == [item.id, item.id]


def test_explicit_reparse_runs_completed_item_without_resuming_background_queue(
    tmp_path: Path,
) -> None:
    client, store, worker, supervisor = _client(tmp_path, paused=True)
    item = _queue(store, tmp_path / "media")
    claimed = store.claim_item(item.id)
    assert claimed is not None
    video_id = uuid4()
    store.complete(item.id, video_id)

    response = client.post(f"/api/v1/library/items/{item.id}/reparse")

    assert response.status_code == 200
    assert response.json()["id"] == str(item.id)
    assert response.json()["status"] == LibraryItemStatus.COMPLETED.value
    assert response.json()["video_id"] == str(video_id)
    assert worker.reparse_calls == [item.id]
    assert supervisor.paused is True

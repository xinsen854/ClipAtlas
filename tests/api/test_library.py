from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from clipatlas.library.models import LibraryItemStatus, ScanReport
from clipatlas.library.store import LibraryStore
from clipatlas.main import create_app


class FakeScanner:
    def __init__(self, report: ScanReport | None = None) -> None:
        self.report = report or ScanReport()
        self.calls = 0

    def scan_all(self) -> ScanReport:
        self.calls += 1
        return self.report


def _client(tmp_path: Path, scanner: FakeScanner | None = None) -> tuple[TestClient, LibraryStore]:
    app = create_app()
    store = LibraryStore(tmp_path / "library.sqlite3")
    app.state.library_store = store
    app.state.library_scanner = scanner or FakeScanner()
    return TestClient(app), store


def test_add_and_list_library_roots(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    client, _store = _client(tmp_path)

    created = client.post(
        "/api/v1/library/roots",
        json={"path": str(media), "recursive": True},
    )

    assert created.status_code == 201
    body = created.json()
    assert body["path"] == str(media.resolve())
    assert body["recursive"] is True
    assert body["enabled"] is True

    listed = client.get("/api/v1/library/roots")
    assert listed.status_code == 200
    assert [root["id"] for root in listed.json()] == [body["id"]]


def test_add_root_rejects_missing_or_file_path(tmp_path: Path) -> None:
    file_path = tmp_path / "not-a-directory.mp4"
    file_path.write_bytes(b"video")
    client, _store = _client(tmp_path)

    missing = client.post(
        "/api/v1/library/roots",
        json={"path": str(tmp_path / "missing"), "recursive": True},
    )
    regular_file = client.post(
        "/api/v1/library/roots",
        json={"path": str(file_path), "recursive": True},
    )

    assert missing.status_code == 422
    assert regular_file.status_code == 422


def test_list_items_and_status_summary(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    movie = media / "movie.mp4"
    movie.write_bytes(b"video")
    client, store = _client(tmp_path)
    root = store.add_root(media)
    stat = movie.stat()
    store.save_observation(root.id, movie, stat.st_size, stat.st_mtime_ns, "fp")

    items = client.get("/api/v1/library/items", params={"status": "QUEUED"})
    summary = client.get("/api/v1/library/summary")

    assert items.status_code == 200
    assert len(items.json()) == 1
    assert items.json()[0]["source_path"] == str(movie.resolve())
    assert items.json()[0]["status"] == "QUEUED"
    assert summary.status_code == 200
    assert summary.json()["QUEUED"] == 1
    assert summary.json()["FAILED"] == 0


def test_get_library_item_detail_and_unknown_item(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    movie = media / "movie.mp4"
    movie.write_bytes(b"video")
    client, store = _client(tmp_path)
    root = store.add_root(media)
    stat = movie.stat()
    store.save_observation(root.id, movie, stat.st_size, stat.st_mtime_ns, "fp")
    item = store.get_item_by_path(movie)
    assert item is not None

    response = client.get(f"/api/v1/library/items/{item.id}")
    assert response.status_code == 200
    assert response.json()["id"] == str(item.id)
    assert response.json()["source_path"] == str(movie.resolve())

    assert client.get(f"/api/v1/library/items/{uuid4()}").status_code == 404


def test_manual_scan_returns_report(tmp_path: Path) -> None:
    scanner = FakeScanner(ScanReport(discovered=2, changed=1, missing=3, unchanged=4))
    client, _store = _client(tmp_path, scanner)

    response = client.post("/api/v1/library/scan")

    assert response.status_code == 200
    assert response.json() == {
        "discovered": 2,
        "changed": 1,
        "missing": 3,
        "unchanged": 4,
    }
    assert scanner.calls == 1


def test_retry_failed_library_item(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    movie = media / "movie.mp4"
    movie.write_bytes(b"video")
    client, store = _client(tmp_path)
    root = store.add_root(media)
    stat = movie.stat()
    store.save_observation(root.id, movie, stat.st_size, stat.st_mtime_ns, "fp")
    item = store.claim_next()
    assert item is not None
    store.fail(item.id, "broken")

    response = client.post(f"/api/v1/library/items/{item.id}/retry")

    assert response.status_code == 200
    assert response.json()["status"] == "QUEUED"
    retried = store.get_item_by_path(movie)
    assert retried is not None
    assert retried.status is LibraryItemStatus.QUEUED
    assert retried.last_error is None


def test_retry_non_failed_item_returns_conflict(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    movie = media / "movie.mp4"
    movie.write_bytes(b"video")
    client, store = _client(tmp_path)
    root = store.add_root(media)
    stat = movie.stat()
    store.save_observation(root.id, movie, stat.st_size, stat.st_mtime_ns, "fp")
    item = store.get_item_by_path(movie)
    assert item is not None

    response = client.post(f"/api/v1/library/items/{item.id}/retry")

    assert response.status_code == 409

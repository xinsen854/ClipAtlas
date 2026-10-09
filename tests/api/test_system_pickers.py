from fastapi import FastAPI
from fastapi.testclient import TestClient

from clipatlas.api.errors import register_error_handlers
from clipatlas.api.routes.system import router as system_router


def _client(monkeypatch, fake_pick) -> TestClient:
    monkeypatch.setattr("clipatlas.api.routes.system.pick", fake_pick)
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(system_router)
    return TestClient(app)


def test_pick_directory_returns_selected_path(monkeypatch) -> None:
    def fake_pick(kind: str) -> str | None:
        assert kind == "directory"
        return "D:/素材库"

    client = _client(monkeypatch, fake_pick)
    response = client.post("/api/v1/system/pick-directory")
    assert response.status_code == 200
    assert response.json() == {"path": "D:/素材库", "cancelled": False}


def test_pick_directory_cancelled_returns_null(monkeypatch) -> None:
    client = _client(monkeypatch, lambda kind: None)
    response = client.post("/api/v1/system/pick-directory")
    assert response.status_code == 200
    assert response.json() == {"path": None, "cancelled": True}


def test_pick_file_uses_file_kind(monkeypatch) -> None:
    captured: list[str] = []

    def fake_pick(kind: str) -> str | None:
        captured.append(kind)
        return "D:/JianyingPro/JianyingPro.exe"

    client = _client(monkeypatch, fake_pick)
    response = client.post("/api/v1/system/pick-file")
    assert response.status_code == 200
    assert captured == ["file"]
    assert response.json()["path"] == "D:/JianyingPro/JianyingPro.exe"


def test_pick_disabled_returns_404(monkeypatch) -> None:
    def fake_pick(kind: str) -> str | None:
        raise AssertionError("must not run")

    app = FastAPI()
    register_error_handlers(app)
    app.include_router(system_router)
    app.state.local_picker_enabled = False
    client = TestClient(app)
    monkeypatch.setattr("clipatlas.api.routes.system.pick", fake_pick)
    response = client.post("/api/v1/system/pick-directory")
    assert response.status_code == 404

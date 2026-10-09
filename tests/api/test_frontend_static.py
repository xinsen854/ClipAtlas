from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from clipatlas.main import create_app
from clipatlas.web import mount_frontend

INDEX_MARKER = "ClipAtlas SPA test shell"


def _build_dist(root: Path) -> Path:
    dist = root / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text(
        f"<!doctype html><html><body>{INDEX_MARKER}</body></html>",
        encoding="utf-8",
    )
    (assets / "app.js").write_text("window.CLIPATLAS_TEST = true;", encoding="utf-8")
    (dist / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    return dist


def test_mount_frontend_serves_spa_routes_without_swallowing_backend(tmp_path: Path) -> None:
    dist = _build_dist(tmp_path)
    app = FastAPI(title="static-test")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/existing")
    async def existing_api() -> dict[str, bool]:
        return {"ok": True}

    mount_frontend(app, dist)
    client = TestClient(app)

    for path in ("/", "/library/items/123", "/rough-cut/xxx"):
        response = client.get(path)
        assert response.status_code == 200
        assert INDEX_MARKER in response.text

    asset_response = client.get("/assets/app.js")
    assert asset_response.status_code == 200
    assert "CLIPATLAS_TEST" in asset_response.text

    logo_response = client.get("/logo.png")
    assert logo_response.status_code == 200
    assert logo_response.headers["content-type"] == "image/png"
    assert logo_response.content == b"\x89PNG\r\n\x1a\n"

    health_response = client.get("/health")
    assert health_response.status_code == 200
    assert health_response.json() == {"status": "ok"}

    api_response = client.get("/api/v1/existing")
    assert api_response.status_code == 200
    assert api_response.json() == {"ok": True}

    docs_response = client.get("/docs")
    assert docs_response.status_code == 200
    assert INDEX_MARKER not in docs_response.text

    openapi_response = client.get("/openapi.json")
    assert openapi_response.status_code == 200
    assert openapi_response.headers["content-type"].startswith("application/json")

    missing_api_response = client.get("/api/v1/not-real")
    assert missing_api_response.status_code == 404
    assert INDEX_MARKER not in missing_api_response.text
    assert missing_api_response.headers["content-type"].startswith("application/json")


def test_mount_frontend_is_noop_when_dist_is_missing(tmp_path: Path) -> None:
    app = FastAPI()

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    mount_frontend(app, tmp_path / "missing-dist")
    client = TestClient(app)

    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/").status_code == 404


def test_mount_frontend_registers_packaged_finecut_without_source_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dist = _build_dist(tmp_path)
    original_is_file = Path.is_file

    def packaged_is_file(path: Path) -> bool:
        if path.as_posix().endswith("modules/finecut/finecut/__init__.py"):
            return False
        return original_is_file(path)

    monkeypatch.setattr(Path, "is_file", packaged_is_file)
    monkeypatch.setenv("CLIPATLAS_FINECUT_DB", str(tmp_path / "finecut.sqlite3"))
    app = FastAPI()

    mount_frontend(app, dist)

    assert "/api/v1/finecut/plans/{plan_id}/timeline" in app.openapi()["paths"]


def test_create_app_uses_frontend_dist_environment_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dist = _build_dist(tmp_path)
    monkeypatch.setenv("CLIPATLAS_FRONTEND_DIST", str(dist))

    client = TestClient(create_app())

    assert (
        client.app.state.export_service._finecut_timeline_store
        is client.app.state.finecut_timeline_store
    )

    root_response = client.get("/")
    assert root_response.status_code == 200
    assert INDEX_MARKER in root_response.text

    health_response = client.get("/health")
    assert health_response.status_code == 200
    assert health_response.headers["content-type"].startswith("application/json")

    missing_api_response = client.get("/api/v1/not-real")
    assert missing_api_response.status_code == 404
    assert INDEX_MARKER not in missing_api_response.text

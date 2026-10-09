from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from clipatlas.api.routes.hypit import router
from clipatlas.hypit.service import HypitService


def client_for(tmp_path: Path) -> TestClient:
    app = FastAPI()
    app.state.hypit_service = HypitService(tmp_path / "data" / "hypit" / "config.json")
    app.include_router(router)
    return TestClient(app)


def test_hypit_config_accepts_an_installed_custom_provider(tmp_path: Path) -> None:
    client = client_for(tmp_path)

    response = client.put(
        "/api/v1/hypit/config",
        json={
            "distribution_root": str(tmp_path / "distribution"),
            "workspace": str(tmp_path / "workspace"),
            "run_file": str(tmp_path / "workspace" / "build.svrun"),
            "endpoint": "video.custom",
            "provider_package": "@example/hypit-provider-video",
            "base_url": "https://video.example.test/v1",
            "base_url_field": "baseUrl",
            "credential_field": "apiKey",
            "provider_config": {"model": "video-1"},
        },
    )

    assert response.status_code == 200
    assert response.json()["provider_package"] == "@example/hypit-provider-video"
    assert response.json()["api_key_configured"] is False
    assert client.get("/api/v1/hypit/status").json()["running"] is False


def test_hypit_start_reports_a_missing_distribution(tmp_path: Path) -> None:
    client = client_for(tmp_path)

    response = client.post("/api/v1/hypit/start")

    assert response.status_code == 409
    assert "Hypit launcher is missing" in response.json()["detail"]


def test_hypit_reference_upload_and_delete_stay_in_hypit_workspace(tmp_path: Path) -> None:
    client = client_for(tmp_path)

    response = client.post(
        "/api/v1/hypit/references",
        files={"file": ("reference.mp4", b"video", "video/mp4")},
    )

    assert response.status_code == 201
    assert response.json()["name"] == "reference.mp4"
    assert [item["name"] for item in client.get("/api/v1/hypit/references").json()] == [
        "reference.mp4"
    ]
    reference = (
        tmp_path
        / "data"
        / "hypit"
        / "workspace"
        / "assets"
        / "references"
        / "reference.mp4"
    )
    assert reference.read_bytes() == b"video"

    assert client.delete("/api/v1/hypit/references/reference.mp4").status_code == 204
    assert not reference.exists()


def test_hypit_inputs_and_brief_are_persisted_in_the_independent_workspace(tmp_path: Path) -> None:
    client = client_for(tmp_path)

    response = client.post(
        "/api/v1/hypit/inputs?kind=products",
        files={"file": ("clipatlas.png", b"image", "image/png")},
    )

    assert response.status_code == 201
    assert response.json()["kind"] == "products"
    assert client.get("/api/v1/hypit/inputs").json()[0]["name"] == "clipatlas.png"

    response = client.put("/api/v1/hypit/brief", json={"text": "保留开场，替换产品"})
    assert response.status_code == 200
    assert client.get("/api/v1/hypit/brief").json() == {"text": "保留开场，替换产品\n"}


def test_hypit_tests_a_transient_wavespeed_key_without_persisting_it(
    tmp_path: Path, monkeypatch
) -> None:
    def get(url: str, **kwargs) -> httpx.Response:
        assert url == "https://api.wavespeed.ai/api/v3/models"
        assert kwargs["headers"] == {"Authorization": "Bearer private-key"}
        return httpx.Response(200, json={"data": []})

    monkeypatch.setattr("clipatlas.hypit.service.httpx.get", get)
    client = client_for(tmp_path)

    response = client.post(
        "/api/v1/hypit/test-connection",
        json={
            "api_key": "private-key",
            "provider_package": "@hypit/provider-wavespeed",
            "base_url": "https://api.wavespeed.ai/api/v3",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "message": "连接成功，API Key 可用。"}
    assert not (tmp_path / "data" / "hypit" / "config.json").exists()

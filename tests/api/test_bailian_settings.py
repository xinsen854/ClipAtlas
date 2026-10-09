import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from clipatlas.main import create_app
from clipatlas.settings.store import SettingsStore


class RecordingBailianProbe:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def detect_bailian_models(self, *, api_key: str, base_url: str):
        self.calls.append((api_key, base_url))
        return SimpleNamespace(
            ok=True,
            code="ok",
            message="模型目录读取成功。",
            models={
                "qwen3-vl-embedding": "available",
                "qwen3.8-flash": "available",
                "qwen3.5-ocr": "unavailable",
                "qwen-audio-3.0-asr-flash": "unavailable",
            },
        )


def _client(tmp_path: Path, monkeypatch) -> tuple[TestClient, SettingsStore]:
    monkeypatch.setenv("CLIPATLAS_PROJECT_DB", str(tmp_path / "projects.sqlite3"))
    monkeypatch.setenv("CLIPATLAS_VIDEO_ROOT", str(tmp_path / "videos"))
    monkeypatch.setenv("CLIPATLAS_LIBRARY_DB", str(tmp_path / "library.sqlite3"))
    monkeypatch.setenv("CLIPATLAS_LIBRARY_CACHE_ROOT", str(tmp_path / "cache"))
    monkeypatch.setenv("CLIPATLAS_NARRATION_ROOT", str(tmp_path / "narration"))
    monkeypatch.setenv("CLIPATLAS_ROUGHCUT_DB", str(tmp_path / "roughcut.sqlite3"))
    monkeypatch.setenv("CLIPATLAS_EXPORT_ROOT", str(tmp_path / "exports"))
    monkeypatch.delenv("CLIPATLAS_BAILIAN_API_KEY", raising=False)
    monkeypatch.delenv("CLIPATLAS_QWEN_API_KEY", raising=False)
    monkeypatch.delenv("CLIPATLAS_EMBEDDING_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    app = create_app()
    store = SettingsStore(tmp_path / "settings.json", environment={})
    app.state.settings_store = store
    return TestClient(app), store


def test_bailian_models_endpoint_uses_unsaved_key_and_never_echoes_it(tmp_path: Path, monkeypatch) -> None:
    client, store = _client(tmp_path, monkeypatch)
    probe = RecordingBailianProbe()
    client.app.state.service_probe = probe

    response = client.post(
        "/api/v1/settings/bailian/models",
        json={
            "api_key": "typed-bailian-secret",
            "base_url": "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        },
    )

    assert response.status_code == 200
    assert probe.calls == [
        (
            "typed-bailian-secret",
            "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        )
    ]
    body = response.json()
    assert body["ok"] is True
    assert body["models"]["qwen3-vl-embedding"] == "available"
    assert body["models"]["qwen3.5-ocr"] == "unavailable"
    assert "typed-bailian-secret" not in json.dumps(body)
    assert store.read_persisted().model_dump(exclude_none=True) == {}


def test_bailian_models_endpoint_reports_missing_key_without_upstream_call(tmp_path: Path, monkeypatch) -> None:
    client, _ = _client(tmp_path, monkeypatch)
    probe = RecordingBailianProbe()
    client.app.state.service_probe = probe

    response = client.post(
        "/api/v1/settings/bailian/models",
        json={
            "base_url": "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        },
    )

    assert response.status_code == 200
    assert response.json()["code"] == "missing_api_key"
    assert set(response.json()["models"].values()) == {"undetected"}
    assert probe.calls == []

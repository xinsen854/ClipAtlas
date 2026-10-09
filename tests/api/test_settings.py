import json
from pathlib import Path

from fastapi.testclient import TestClient

from clipatlas.main import create_app
from clipatlas.settings.models import SettingsPatch
from clipatlas.settings.probe import ModelListResult, ServiceProbeRequest, ServiceProbeResult
from clipatlas.settings.store import SettingsStore


class RecordingProbe:
    def __init__(self) -> None:
        self.connection_requests: list[ServiceProbeRequest] = []
        self.model_requests: list[ServiceProbeRequest] = []

    async def test_connection(self, request: ServiceProbeRequest) -> ServiceProbeResult:
        self.connection_requests.append(request)
        return ServiceProbeResult(ok=True, code="ok", message="连接成功。")

    async def list_models(self, request: ServiceProbeRequest) -> ModelListResult:
        self.model_requests.append(request)
        return ModelListResult(supported=True, models=["model-a", "model-b"])


def _client(tmp_path: Path, monkeypatch) -> tuple[TestClient, SettingsStore]:
    monkeypatch.setenv("CLIPATLAS_PROJECT_DB", str(tmp_path / "projects.sqlite3"))
    monkeypatch.setenv("CLIPATLAS_VIDEO_ROOT", str(tmp_path / "videos"))
    monkeypatch.setenv("CLIPATLAS_LIBRARY_DB", str(tmp_path / "library.sqlite3"))
    monkeypatch.setenv("CLIPATLAS_LIBRARY_CACHE_ROOT", str(tmp_path / "cache"))
    monkeypatch.setenv("CLIPATLAS_NARRATION_ROOT", str(tmp_path / "narration"))
    monkeypatch.setenv("CLIPATLAS_ROUGHCUT_DB", str(tmp_path / "roughcut.sqlite3"))
    monkeypatch.setenv("CLIPATLAS_EXPORT_ROOT", str(tmp_path / "exports"))
    monkeypatch.delenv("CLIPATLAS_LIBRARY_PROVIDER", raising=False)
    monkeypatch.delenv("CLIPATLAS_QWEN_API_KEY", raising=False)
    monkeypatch.delenv("CLIPATLAS_EMBEDDING_API_KEY", raising=False)
    monkeypatch.delenv("CLIPATLAS_SPEECH_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    app = create_app()
    store = SettingsStore(tmp_path / "settings.json", environment={})
    app.state.settings_store = store
    return TestClient(app), store


def test_get_settings_never_echoes_secret_plaintext(tmp_path: Path, monkeypatch) -> None:
    client, store = _client(tmp_path, monkeypatch)
    store.update(
        SettingsPatch(
            qwen_api_key="secret-qwen-key",
            qwen_default_model="file-model",
        )
    )

    response = client.get("/api/v1/settings")

    assert response.status_code == 200
    body = response.json()
    serialized = json.dumps(body)
    assert body["qwen_default_model"]["value"] == "file-model"
    assert body["qwen_default_model"]["source"] == "file"
    assert body["qwen_api_key_configured"] is True
    assert body["qwen_api_key_source"] == "file"
    assert "secret-qwen-key" not in serialized


def test_patch_settings_persists_values_without_echoing_new_secret(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, store = _client(tmp_path, monkeypatch)

    response = client.patch(
        "/api/v1/settings",
        json={
            "qwen_default_model": "new-model",
            "qwen_api_key": "new-secret-key",
            "jianying_executable": "C:/Program Files/Jianying/JianyingPro.exe",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["restart_required"] is True
    assert body["settings"]["qwen_default_model"] == {
        "value": "new-model",
        "source": "file",
    }
    assert body["settings"]["qwen_api_key_configured"] is True
    assert body["settings"]["qwen_api_key_source"] == "file"
    assert "new-secret-key" not in json.dumps(body)
    persisted = store.read_persisted()
    assert persisted.qwen_api_key == "new-secret-key"
    assert persisted.qwen_default_model == "new-model"


def test_patch_blank_secret_keeps_existing_and_explicit_clear_removes_it(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, store = _client(tmp_path, monkeypatch)
    store.update(SettingsPatch(qwen_api_key="existing-secret"))

    blank = client.patch(
        "/api/v1/settings",
        json={"qwen_api_key": "   ", "qwen_default_model": "model-b"},
    )
    assert blank.status_code == 200
    assert store.read_persisted().qwen_api_key == "existing-secret"
    assert "existing-secret" not in json.dumps(blank.json())

    cleared = client.patch(
        "/api/v1/settings",
        json={"clear_qwen_api_key": True},
    )
    assert cleared.status_code == 200
    assert store.read_persisted().qwen_api_key is None
    assert cleared.json()["settings"]["qwen_api_key_configured"] is False


def test_patch_settings_rejects_unknown_keys(tmp_path: Path, monkeypatch) -> None:
    client, _ = _client(tmp_path, monkeypatch)

    response = client.patch(
        "/api/v1/settings",
        json={"arbitrary_environment_variable": "unsafe"},
    )

    assert response.status_code == 422


def test_connection_probe_prefers_typed_key_without_persisting_it(tmp_path: Path, monkeypatch) -> None:
    client, store = _client(tmp_path, monkeypatch)
    store.update(SettingsPatch(qwen_api_key="saved-secret"))
    probe = RecordingProbe()
    client.app.state.service_probe = probe

    response = client.post(
        "/api/v1/settings/test-connection",
        json={
            "service": "video",
            "provider": "qwen",
            "api_key": "typed-secret",
            "base_url": "https://provider.example/v1",
            "model": "model-a",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "code": "ok", "message": "连接成功。"}
    assert probe.connection_requests[0].api_key == "typed-secret"
    assert store.read_persisted().qwen_api_key == "saved-secret"
    serialized = json.dumps(response.json())
    assert "typed-secret" not in serialized
    assert "saved-secret" not in serialized


def test_connection_probe_uses_saved_or_environment_key_when_input_is_blank(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, store = _client(tmp_path, monkeypatch)
    probe = RecordingProbe()
    client.app.state.service_probe = probe
    store.update(SettingsPatch(embedding_api_key="saved-embedding-secret"))

    saved_response = client.post(
        "/api/v1/settings/test-connection",
        json={
            "service": "embedding",
            "provider": "qwen-embedding",
            "base_url": "https://provider.example/v1",
            "model": "embed-a",
            "dimensions": 1024,
        },
    )
    assert saved_response.status_code == 200
    assert probe.connection_requests[-1].api_key == "saved-embedding-secret"

    store.environment["DASHSCOPE_API_KEY"] = "environment-secret"
    environment_response = client.post(
        "/api/v1/settings/test-connection",
        json={
            "service": "speech",
            "provider": "dashscope",
            "base_url": "https://provider.example/tts",
            "model": "speech-a",
        },
    )
    assert environment_response.status_code == 200
    assert probe.connection_requests[-1].api_key == "environment-secret"
    assert "environment-secret" not in json.dumps(environment_response.json())


def test_connection_probe_reports_missing_key_without_calling_upstream(tmp_path: Path, monkeypatch) -> None:
    client, _ = _client(tmp_path, monkeypatch)
    probe = RecordingProbe()
    client.app.state.service_probe = probe

    response = client.post(
        "/api/v1/settings/test-connection",
        json={
            "service": "video",
            "provider": "qwen",
            "base_url": "https://provider.example/v1",
            "model": "model-a",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": False,
        "code": "missing_api_key",
        "message": "请先输入或保存 API Key。",
    }
    assert probe.connection_requests == []


def test_model_listing_uses_local_probe_and_never_echoes_key(tmp_path: Path, monkeypatch) -> None:
    client, _ = _client(tmp_path, monkeypatch)
    probe = RecordingProbe()
    client.app.state.service_probe = probe

    response = client.post(
        "/api/v1/settings/models",
        json={
            "service": "video",
            "provider": "qwen",
            "api_key": "typed-secret",
            "base_url": "https://provider.example/v1",
            "model": "model-a",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"supported": True, "models": ["model-a", "model-b"]}
    assert probe.model_requests[0].api_key == "typed-secret"
    assert "typed-secret" not in json.dumps(response.json())

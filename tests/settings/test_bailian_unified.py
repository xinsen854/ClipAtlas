import json
from pathlib import Path

import httpx
import pytest

from clipatlas.settings.models import SettingsPatch
from clipatlas.settings.probe import ServiceProbe
from clipatlas.settings.store import SettingsStore

ALIYUN_COMPATIBLE = "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
ALIYUN_NATIVE = "https://workspace.cn-beijing.maas.aliyuncs.com/api/v1"


def test_bailian_settings_are_single_secret_and_never_echo_plaintext(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "settings.json", environment={})

    store.update(
        SettingsPatch(
            bailian_api_key="bailian-secret",
            bailian_base_url=ALIYUN_COMPATIBLE,
        )
    )
    snapshot = store.public_snapshot()

    assert snapshot.bailian_base_url.value == ALIYUN_COMPATIBLE
    assert snapshot.bailian_base_url.source == "file"
    assert snapshot.bailian_api_key_configured is True
    assert snapshot.bailian_api_key_source == "file"
    assert "bailian-secret" not in snapshot.model_dump_json()
    assert "bailian-secret" not in json.dumps(snapshot.model_dump())


def test_legacy_embedding_aliyun_config_is_safe_bailian_migration_candidate(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "settings.json", environment={})
    store.update(
        SettingsPatch(
            embedding_api_key="legacy-embedding-secret",
            embedding_base_url=ALIYUN_COMPATIBLE,
        )
    )

    snapshot = store.public_snapshot()

    assert snapshot.bailian_base_url.value == ALIYUN_COMPATIBLE
    assert snapshot.bailian_base_url.source == "file"
    assert snapshot.bailian_api_key_configured is True
    assert snapshot.bailian_api_key_source == "file"
    assert store.resolve_secret("bailian_api_key") == "legacy-embedding-secret"


def test_third_party_qwen_config_is_never_auto_migrated_to_bailian(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "settings.json", environment={})
    store.update(
        SettingsPatch(
            qwen_api_key="third-party-secret",
            qwen_base_url="https://shu26.cfd/v1",
        )
    )

    snapshot = store.public_snapshot()

    assert snapshot.bailian_api_key_configured is False
    assert snapshot.bailian_api_key_source == "default"
    assert store.resolve_secret("bailian_api_key") is None
    assert "shu26.cfd" not in str(snapshot.bailian_base_url.value)


def test_bailian_settings_inject_compatible_runtime_credentials_without_touching_tts(
    tmp_path: Path,
) -> None:
    environment: dict[str, str] = {
        "CLIPATLAS_SPEECH_API_KEY": "speech-secret",
        "CLIPATLAS_SPEECH_BASE_URL": "https://speech.example/tts",
    }
    store = SettingsStore(tmp_path / "settings.json", environment=environment)
    store.update(
        SettingsPatch(
            bailian_api_key="bailian-secret",
            bailian_base_url=ALIYUN_COMPATIBLE,
        )
    )

    store.apply_missing_environment()

    assert environment["CLIPATLAS_BAILIAN_API_KEY"] == "bailian-secret"
    assert environment["CLIPATLAS_BAILIAN_BASE_URL"] == ALIYUN_COMPATIBLE
    assert environment["CLIPATLAS_QWEN_API_KEY"] == "bailian-secret"
    assert environment["CLIPATLAS_QWEN_BASE_URL"] == ALIYUN_COMPATIBLE
    assert environment["CLIPATLAS_EMBEDDING_API_KEY"] == "bailian-secret"
    assert environment["CLIPATLAS_EMBEDDING_BASE_URL"] == ALIYUN_COMPATIBLE
    assert environment["CLIPATLAS_SPEECH_API_KEY"] == "speech-secret"
    assert environment["CLIPATLAS_SPEECH_BASE_URL"] == "https://speech.example/tts"


@pytest.mark.asyncio
async def test_bailian_model_detection_queries_each_fixed_model_exactly() -> None:
    captured: list[httpx.Request] = []
    available = {
        "qwen3-vl-embedding",
        "qwen3.8-flash",
        "qwen-audio-3.0-asr-flash",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        model_id = request.url.params.get("model")
        models = [{"model": model_id}] if model_id in available else []
        return httpx.Response(
            200,
            json={
                "success": True,
                "output": {
                    "models": models,
                },
            },
        )

    probe = ServiceProbe(transport=httpx.MockTransport(handler))
    result = await probe.detect_bailian_models(
        api_key="bailian-secret",
        base_url=ALIYUN_COMPATIBLE,
    )

    assert result.ok is True
    assert result.code == "ok"
    assert len(captured) == 4
    assert [request.url.params.get("model") for request in captured] == [
        "qwen3-vl-embedding",
        "qwen3.8-flash",
        "qwen3.5-ocr",
        "qwen-audio-3.0-asr-flash",
    ]
    for request in captured:
        assert request.url.path == "/api/v1/models"
        assert request.url.params.get("page_no") == "1"
        assert request.url.params.get("page_size") == "1"
        assert request.headers["authorization"] == "Bearer bailian-secret"
    assert result.models == {
        "video_embedding": "available",
        "video_understanding": "available",
        "ocr": "unavailable",
        "asr": "available",
        "media_type": "available",
        "director": "available",
    }


@pytest.mark.asyncio
async def test_bailian_model_detection_refuses_third_party_base_url_before_network_call() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"data": []})

    probe = ServiceProbe(transport=httpx.MockTransport(handler))
    result = await probe.detect_bailian_models(
        api_key="bailian-secret",
        base_url="https://third-party.example/v1",
    )

    assert result.ok is False
    assert result.code == "invalid_base_url"
    assert calls == 0
    assert set(result.models.values()) == {"undetected"}

from pathlib import Path

import pytest

import clipatlas.main as main_module
from clipatlas.app_state import (
    _build_embedding_provider,
    build_provider_registry,
    build_settings_store,
    build_speech_provider_registry,
)
from clipatlas.settings.models import SettingsPatch
from clipatlas.settings.store import SettingsStore


def test_build_settings_store_uses_configured_file_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings_path = tmp_path / "custom" / "settings.json"
    monkeypatch.setenv("CLIPATLAS_SETTINGS_FILE", str(settings_path))

    store = build_settings_store()
    store.update(SettingsPatch(qwen_default_model="file-model"))

    assert settings_path.exists()
    assert store.read_persisted().qwen_default_model == "file-model"


def test_create_app_applies_settings_before_existing_runtime_builders(monkeypatch) -> None:
    class StopBuild(RuntimeError):
        pass

    class FakeSettingsStore:
        applied = False

        def apply_missing_environment(self) -> None:
            self.applied = True

    fake_store = FakeSettingsStore()

    def stop_at_first_existing_builder():
        assert fake_store.applied is True
        raise StopBuild

    monkeypatch.setattr(main_module, "build_settings_store", lambda: fake_store)
    monkeypatch.setattr(
        main_module,
        "build_project_store",
        stop_at_first_existing_builder,
    )

    with pytest.raises(StopBuild):
        main_module.create_app()


def test_bailian_runtime_config_takes_priority_over_legacy_non_tts_env(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bailian_base = "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    monkeypatch.setenv("CLIPATLAS_BAILIAN_API_KEY", "bailian-secret")
    monkeypatch.setenv("CLIPATLAS_BAILIAN_BASE_URL", bailian_base)
    monkeypatch.setenv("CLIPATLAS_QWEN_API_KEY", "legacy-qwen-secret")
    monkeypatch.setenv("CLIPATLAS_QWEN_BASE_URL", "https://shu26.cfd/v1")
    monkeypatch.setenv("CLIPATLAS_EMBEDDING_API_KEY", "legacy-embedding-secret")
    monkeypatch.setenv(
        "CLIPATLAS_EMBEDDING_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    SettingsStore(tmp_path / "settings.json").apply_missing_environment()
    qwen = build_provider_registry().get("qwen")
    embedding = _build_embedding_provider()

    assert qwen is not None
    assert qwen._api_key == "bailian-secret"
    assert qwen._base_url == bailian_base
    assert embedding is not None
    assert embedding._api_key == "bailian-secret"
    assert embedding._base_url == bailian_base


def test_dashscope_speech_runtime_normalizes_compatible_mode_url(monkeypatch) -> None:
    monkeypatch.setenv("CLIPATLAS_SPEECH_API_KEY", "speech-secret")
    monkeypatch.setenv(
        "CLIPATLAS_SPEECH_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    monkeypatch.setenv("CLIPATLAS_SPEECH_MODEL", "")

    provider = build_speech_provider_registry().get("dashscope")

    assert provider is not None
    assert provider._base_url == (
        "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer"
    )
    assert provider._model == "cosyvoice-v3.5-flash"

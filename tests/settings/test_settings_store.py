import json
from pathlib import Path

from clipatlas.settings.models import SettingsPatch
from clipatlas.settings.store import SettingsStore
from clipatlas.exports.models import DEFAULT_JIANYING_DRAFT_ROOT


def test_missing_file_reads_as_empty_persisted_settings(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "settings.json", environment={})

    persisted = store.read_persisted()

    assert persisted.model_dump(exclude_none=True) == {}


def test_default_model_stack_uses_dashscope_qwen_3_8_embedding_and_tts(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "settings.json", environment={})

    snapshot = store.public_snapshot()

    assert snapshot.qwen_default_model.value == "qwen3.8-flash"
    assert snapshot.qwen_long_context_model.value == "qwen3.8-flash"
    assert snapshot.embedding_model.value == "text-embedding-v4"
    assert snapshot.embedding_dimensions.value == 1024
    assert snapshot.speech_model.value == "cosyvoice-v3.5-flash"
    assert snapshot.jianying_draft_root.value == DEFAULT_JIANYING_DRAFT_ROOT


def test_update_is_atomic_preserves_omitted_fields_and_allows_non_secret_clear(
    tmp_path: Path,
) -> None:
    path = tmp_path / "nested" / "settings.json"
    store = SettingsStore(path, environment={})

    first = store.update(
        SettingsPatch(
            library_provider="qwen",
            qwen_base_url="https://example.invalid/v1",
            qwen_default_model="model-a",
        )
    )
    assert first.library_provider == "qwen"
    assert first.qwen_default_model == "model-a"
    assert path.exists()
    assert not path.with_suffix(path.suffix + ".tmp").exists()
    assert json.loads(path.read_text(encoding="utf-8"))["qwen_default_model"] == "model-a"

    second = store.update(SettingsPatch(qwen_base_url=None, qwen_default_model="model-b"))
    assert second.library_provider == "qwen"
    assert second.qwen_base_url is None
    assert second.qwen_default_model == "model-b"


def test_secret_blank_means_unchanged_and_explicit_clear_removes_secret(
    tmp_path: Path,
) -> None:
    store = SettingsStore(tmp_path / "settings.json", environment={})
    store.update(SettingsPatch(qwen_api_key="secret-qwen-key"))

    blank_update = store.update(SettingsPatch(qwen_api_key="   "))
    assert blank_update.qwen_api_key == "secret-qwen-key"

    cleared = store.update(SettingsPatch(clear_qwen_api_key=True))
    assert cleared.qwen_api_key is None
    assert "secret-qwen-key" not in (tmp_path / "settings.json").read_text(encoding="utf-8")


def test_public_snapshot_uses_environment_precedence_without_echoing_secrets(
    tmp_path: Path,
) -> None:
    environment = {"CLIPATLAS_QWEN_DEFAULT_MODEL": "env-model"}
    store = SettingsStore(tmp_path / "settings.json", environment=environment)
    store.update(
        SettingsPatch(
            qwen_api_key="secret-qwen-key",
            qwen_default_model="file-model",
            jianying_draft_root="D:/ClipAtlasDrafts",
        )
    )

    snapshot = store.public_snapshot()
    serialized = snapshot.model_dump_json()

    assert snapshot.qwen_default_model.value == "env-model"
    assert snapshot.qwen_default_model.source == "environment"
    assert snapshot.jianying_draft_root.value == "D:/ClipAtlasDrafts"
    assert snapshot.jianying_draft_root.source == "file"
    assert snapshot.qwen_api_key_configured is True
    assert snapshot.qwen_api_key_source == "file"
    assert "secret-qwen-key" not in serialized


def test_apply_missing_environment_never_overwrites_process_environment(
    tmp_path: Path,
) -> None:
    environment = {"CLIPATLAS_QWEN_DEFAULT_MODEL": "env-model"}
    store = SettingsStore(tmp_path / "settings.json", environment=environment)
    store.update(
        SettingsPatch(
            library_provider="qwen",
            qwen_api_key="file-secret",
            qwen_default_model="file-model",
        )
    )

    store.apply_missing_environment()

    assert environment["CLIPATLAS_LIBRARY_PROVIDER"] == "qwen"
    assert environment["CLIPATLAS_QWEN_API_KEY"] == "file-secret"
    assert environment["CLIPATLAS_QWEN_DEFAULT_MODEL"] == "env-model"


def test_runtime_injected_values_remain_file_sourced_and_follow_later_file_updates(
    tmp_path: Path,
) -> None:
    environment: dict[str, str] = {}
    store = SettingsStore(tmp_path / "settings.json", environment=environment)
    store.update(
        SettingsPatch(
            qwen_api_key="file-secret-a",
            qwen_default_model="file-model-a",
        )
    )

    store.apply_missing_environment()
    initial = store.public_snapshot()

    assert initial.qwen_default_model.value == "file-model-a"
    assert initial.qwen_default_model.source == "file"
    assert initial.qwen_api_key_source == "file"

    store.update(
        SettingsPatch(
            qwen_api_key="file-secret-b",
            qwen_default_model="file-model-b",
        )
    )
    updated = store.public_snapshot()

    assert environment["CLIPATLAS_QWEN_DEFAULT_MODEL"] == "file-model-a"
    assert updated.qwen_default_model.value == "file-model-b"
    assert updated.qwen_default_model.source == "file"
    assert updated.qwen_api_key_configured is True
    assert updated.qwen_api_key_source == "file"
    assert "file-secret-b" not in updated.model_dump_json()


def test_saved_bailian_settings_override_stale_environment_for_runtime(tmp_path: Path) -> None:
    environment = {
        "CLIPATLAS_BAILIAN_API_KEY": "stale-bailian-key",
        "CLIPATLAS_BAILIAN_BASE_URL": "https://stale.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        "DASHSCOPE_API_KEY": "stale-dashscope-key",
    }
    store = SettingsStore(tmp_path / "settings.json", environment=environment)
    store.update(
        SettingsPatch(
            bailian_api_key="saved-bailian-key",
            bailian_base_url="https://saved.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        )
    )

    store.apply_missing_environment()
    snapshot = store.public_snapshot()

    assert store.resolve_secret("bailian_api_key") == "saved-bailian-key"
    assert snapshot.bailian_api_key_source == "file"
    assert snapshot.bailian_base_url.value == "https://saved.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    assert snapshot.bailian_base_url.source == "file"
    assert environment["CLIPATLAS_BAILIAN_API_KEY"] == "saved-bailian-key"
    assert environment["CLIPATLAS_BAILIAN_BASE_URL"] == "https://saved.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    assert environment["CLIPATLAS_QWEN_API_KEY"] == "saved-bailian-key"
    assert environment["CLIPATLAS_EMBEDDING_API_KEY"] == "saved-bailian-key"


def test_saved_speech_key_overrides_stale_dashscope_environment(tmp_path: Path) -> None:
    store = SettingsStore(
        tmp_path / "settings.json",
        environment={"DASHSCOPE_API_KEY": "stale-dashscope-key"},
    )
    store.update(SettingsPatch(speech_api_key="saved-speech-key"))

    assert store.resolve_secret("speech_api_key") == "saved-speech-key"
    assert store.public_snapshot().speech_api_key_source == "file"


def test_bailian_environment_remains_authoritative_without_saved_settings(tmp_path: Path) -> None:
    environment = {
        "CLIPATLAS_BAILIAN_API_KEY": "env-bailian-key",
        "CLIPATLAS_BAILIAN_BASE_URL": "https://env.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    }
    store = SettingsStore(tmp_path / "settings.json", environment=environment)

    store.apply_missing_environment()
    snapshot = store.public_snapshot()

    assert store.resolve_secret("bailian_api_key") == "env-bailian-key"
    assert snapshot.bailian_api_key_source == "environment"
    assert snapshot.bailian_base_url.value == "https://env.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    assert snapshot.bailian_base_url.source == "environment"
    assert environment["CLIPATLAS_BAILIAN_API_KEY"] == "env-bailian-key"
    assert environment["CLIPATLAS_BAILIAN_BASE_URL"] == "https://env.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"

from __future__ import annotations

import json
import os
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any, Literal

from clipatlas.settings.bailian import derive_bailian_endpoints, is_aliyun_bailian_url
from clipatlas.exports.models import DEFAULT_JIANYING_DRAFT_ROOT
from clipatlas.settings.models import (
    PersistedSettings,
    PublicSettings,
    PublicSettingValue,
    SettingSource,
    SettingsPatch,
)

_QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_BAILIAN_BASE_URL = _QWEN_BASE_URL
_SPEECH_BASE_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer"
)

_FIELD_TO_ENV = {
    "library_provider": "CLIPATLAS_LIBRARY_PROVIDER",
    "library_cache_root": "CLIPATLAS_LIBRARY_CACHE_ROOT",
    "bailian_api_key": "CLIPATLAS_BAILIAN_API_KEY",
    "bailian_base_url": "CLIPATLAS_BAILIAN_BASE_URL",
    "qwen_api_key": "CLIPATLAS_QWEN_API_KEY",
    "qwen_base_url": "CLIPATLAS_QWEN_BASE_URL",
    "qwen_default_model": "CLIPATLAS_QWEN_DEFAULT_MODEL",
    "qwen_long_context_model": "CLIPATLAS_QWEN_LONG_CONTEXT_MODEL",
    "embedding_api_key": "CLIPATLAS_EMBEDDING_API_KEY",
    "embedding_base_url": "CLIPATLAS_EMBEDDING_BASE_URL",
    "embedding_model": "CLIPATLAS_EMBEDDING_MODEL",
    "embedding_dimensions": "CLIPATLAS_EMBEDDING_DIMENSIONS",
    "speech_provider": "CLIPATLAS_SPEECH_PROVIDER",
    "speech_api_key": "CLIPATLAS_SPEECH_API_KEY",
    "speech_base_url": "CLIPATLAS_SPEECH_BASE_URL",
    "speech_model": "CLIPATLAS_SPEECH_MODEL",
    "jianying_draft_root": "CLIPATLAS_JIANYING_DRAFT_ROOT",
    "jianying_install_dir": "CLIPATLAS_JIANYING_INSTALL_DIR",
    "jianying_user_data": "CLIPATLAS_JIANYING_USER_DATA",
    "jianying_mode": "CLIPATLAS_JIANYING_MODE",
    "jianying_executable": "CLIPATLAS_JIANYING_EXECUTABLE",
}

_SECRET_FIELDS = {
    "bailian_api_key": "clear_bailian_api_key",
    "qwen_api_key": "clear_qwen_api_key",
    "embedding_api_key": "clear_embedding_api_key",
    "speech_api_key": "clear_speech_api_key",
}

_DEFAULTS: dict[str, str | int | None] = {
    "library_provider": None,
    "library_cache_root": "./data/library-cache",
    "bailian_base_url": _BAILIAN_BASE_URL,
    "qwen_base_url": _QWEN_BASE_URL,
    "qwen_default_model": "qwen3.8-flash",
    "qwen_long_context_model": "qwen3.8-flash",
    "embedding_base_url": _QWEN_BASE_URL,
    "embedding_model": "text-embedding-v4",
    "embedding_dimensions": 1024,
    "speech_provider": "dashscope",
    "speech_base_url": _SPEECH_BASE_URL,
    "speech_model": "cosyvoice-v3.5-flash",
    "jianying_draft_root": DEFAULT_JIANYING_DRAFT_ROOT,
    "jianying_install_dir": None,
    "jianying_user_data": None,
    "jianying_mode": "portable",
    "jianying_executable": None,
}

SecretFieldName = Literal[
    "bailian_api_key",
    "qwen_api_key",
    "embedding_api_key",
    "speech_api_key",
]


class SettingsStore:
    def __init__(
        self,
        path: Path,
        *,
        environment: MutableMapping[str, str] | None = None,
    ) -> None:
        self._path = path
        self.environment = os.environ if environment is None else environment
        self._injected_environment: set[str] = set()

    def read_persisted(self) -> PersistedSettings:
        if not self._path.exists():
            return PersistedSettings()
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        return PersistedSettings.model_validate(payload)

    def update(self, patch: SettingsPatch) -> PersistedSettings:
        current = self.read_persisted().model_dump()
        fields_set = patch.model_fields_set

        for field_name in PersistedSettings.model_fields:
            if field_name in _SECRET_FIELDS:
                clear_field = _SECRET_FIELDS[field_name]
                if getattr(patch, clear_field):
                    current[field_name] = None
                    continue
                if field_name not in fields_set:
                    continue
                secret_value = getattr(patch, field_name)
                if secret_value is None or not secret_value.strip():
                    continue
                current[field_name] = secret_value.strip()
                continue

            if field_name in fields_set:
                current[field_name] = getattr(patch, field_name)

        persisted = PersistedSettings.model_validate(current)
        self._write_atomic(persisted)
        return persisted

    def apply_missing_environment(self) -> None:
        persisted = self.read_persisted()
        for field_name, env_name in _FIELD_TO_ENV.items():
            if env_name in self.environment:
                continue
            value = getattr(persisted, field_name)
            if value is None:
                continue
            self.environment[env_name] = str(value)
            self._injected_environment.add(env_name)

        bailian_key = self.resolve_secret("bailian_api_key")
        bailian_base = self._effective_bailian_base(persisted).value
        if bailian_key is None or not isinstance(bailian_base, str):
            return
        try:
            compatible_base = derive_bailian_endpoints(bailian_base).openai_compatible
        except ValueError:
            return

        saved_bailian_key = (
            persisted.bailian_api_key is not None
            and bool(persisted.bailian_api_key.strip())
        )
        saved_bailian_base = persisted.bailian_base_url is not None
        for env_name, value, force in (
            ("CLIPATLAS_BAILIAN_API_KEY", bailian_key, saved_bailian_key),
            ("CLIPATLAS_BAILIAN_BASE_URL", compatible_base, saved_bailian_base),
            ("CLIPATLAS_QWEN_API_KEY", bailian_key, True),
            ("CLIPATLAS_QWEN_BASE_URL", compatible_base, True),
            ("CLIPATLAS_EMBEDDING_API_KEY", bailian_key, True),
            ("CLIPATLAS_EMBEDDING_BASE_URL", compatible_base, True),
        ):
            self._inject_compatibility_value(env_name, value, force=force)

    def resolve_secret(self, field_name: SecretFieldName) -> str | None:
        if field_name == "bailian_api_key":
            return self._resolve_bailian_secret()

        persisted = self.read_persisted()
        if (
            field_name == "speech_api_key"
            and persisted.speech_api_key is not None
            and persisted.speech_api_key.strip()
        ):
            return persisted.speech_api_key.strip()

        env_name = _FIELD_TO_ENV[field_name]
        direct_value = self.environment.get(env_name, "").strip()
        if direct_value and env_name not in self._injected_environment:
            return direct_value

        if field_name == "speech_api_key":
            bailian_value = self._resolve_bailian_secret()
            if bailian_value is not None:
                return bailian_value

        dashscope_value = self.environment.get("DASHSCOPE_API_KEY", "").strip()
        if dashscope_value:
            return dashscope_value

        if field_name == "qwen_api_key":
            persisted_value = persisted.qwen_api_key
        elif field_name == "embedding_api_key":
            persisted_value = persisted.embedding_api_key
        else:
            persisted_value = persisted.speech_api_key
        if persisted_value is not None and persisted_value.strip():
            return persisted_value.strip()
        return None

    def public_snapshot(self) -> PublicSettings:
        persisted = self.read_persisted()
        values = {
            field_name: self._public_value(
                field_name,
                getattr(persisted, field_name),
                _DEFAULTS[field_name],
            )
            for field_name in _DEFAULTS
        }
        values["bailian_base_url"] = self._effective_bailian_base(persisted)
        bailian_configured, bailian_source = self._bailian_secret_status(persisted)
        qwen_configured, qwen_source = self._secret_status(
            "qwen_api_key", persisted.qwen_api_key
        )
        embedding_configured, embedding_source = self._secret_status(
            "embedding_api_key", persisted.embedding_api_key
        )
        speech_configured, speech_source = self._secret_status(
            "speech_api_key", persisted.speech_api_key
        )
        return PublicSettings(
            **values,
            bailian_api_key_configured=bailian_configured,
            bailian_api_key_source=bailian_source,
            qwen_api_key_configured=qwen_configured,
            qwen_api_key_source=qwen_source,
            embedding_api_key_configured=embedding_configured,
            embedding_api_key_source=embedding_source,
            speech_api_key_configured=speech_configured,
            speech_api_key_source=speech_source,
        )

    def _resolve_bailian_secret(self) -> str | None:
        persisted = self.read_persisted()
        if persisted.bailian_api_key is not None and persisted.bailian_api_key.strip():
            return persisted.bailian_api_key.strip()

        env_name = _FIELD_TO_ENV["bailian_api_key"]
        direct_value = self.environment.get(env_name, "").strip()
        if direct_value and env_name not in self._injected_environment:
            return direct_value

        dashscope_value = self.environment.get("DASHSCOPE_API_KEY", "").strip()
        if dashscope_value:
            return dashscope_value

        legacy_base = self._public_value(
            "embedding_base_url",
            persisted.embedding_base_url,
            _DEFAULTS["embedding_base_url"],
        )
        if not is_aliyun_bailian_url(str(legacy_base.value or "")):
            return None

        legacy_env_name = _FIELD_TO_ENV["embedding_api_key"]
        legacy_direct = self.environment.get(legacy_env_name, "").strip()
        if legacy_direct and legacy_env_name not in self._injected_environment:
            return legacy_direct
        if persisted.embedding_api_key is not None and persisted.embedding_api_key.strip():
            return persisted.embedding_api_key.strip()
        return None

    def _effective_bailian_base(self, persisted: PersistedSettings) -> PublicSettingValue:
        if persisted.bailian_base_url is not None:
            return PublicSettingValue(value=persisted.bailian_base_url, source="file")

        env_name = _FIELD_TO_ENV["bailian_base_url"]
        if env_name in self.environment and env_name not in self._injected_environment:
            return PublicSettingValue(value=self.environment[env_name], source="environment")

        explicit = PublicSettingValue(value=_DEFAULTS["bailian_base_url"], source="default")
        legacy = self._public_value(
            "embedding_base_url",
            persisted.embedding_base_url,
            _DEFAULTS["embedding_base_url"],
        )
        if is_aliyun_bailian_url(str(legacy.value or "")):
            return legacy
        return explicit

    def _bailian_secret_status(
        self,
        persisted: PersistedSettings,
    ) -> tuple[bool, SettingSource]:
        if persisted.bailian_api_key is not None and persisted.bailian_api_key.strip():
            return True, "file"

        env_name = _FIELD_TO_ENV["bailian_api_key"]
        direct_value = self.environment.get(env_name, "").strip()
        if direct_value and env_name not in self._injected_environment:
            return True, "environment"
        if self.environment.get("DASHSCOPE_API_KEY", "").strip():
            return True, "environment"

        legacy_base = self._public_value(
            "embedding_base_url",
            persisted.embedding_base_url,
            _DEFAULTS["embedding_base_url"],
        )
        if not is_aliyun_bailian_url(str(legacy_base.value or "")):
            return False, "default"

        legacy_env_name = _FIELD_TO_ENV["embedding_api_key"]
        legacy_direct = self.environment.get(legacy_env_name, "").strip()
        if legacy_direct and legacy_env_name not in self._injected_environment:
            return True, "environment"
        if persisted.embedding_api_key is not None and persisted.embedding_api_key.strip():
            return True, "file"
        return False, "default"

    def _inject_compatibility_value(
        self,
        env_name: str,
        value: str,
        *,
        force: bool,
    ) -> None:
        if not force and env_name in self.environment and env_name not in self._injected_environment:
            return
        self.environment[env_name] = value
        self._injected_environment.add(env_name)

    def _write_atomic(self, persisted: PersistedSettings) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        payload = persisted.model_dump(exclude_none=True)
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(self._path)

    def _public_value(
        self,
        field_name: str,
        persisted_value: Any,
        default_value: str | int | None,
    ) -> PublicSettingValue:
        env_name = _FIELD_TO_ENV[field_name]
        if env_name in self.environment and env_name not in self._injected_environment:
            raw_environment_value = self.environment[env_name]
            value: str | int | None
            if field_name == "embedding_dimensions":
                value = int(raw_environment_value)
            else:
                value = raw_environment_value
            return PublicSettingValue(value=value, source="environment")
        if persisted_value is not None:
            return PublicSettingValue(value=persisted_value, source="file")
        return PublicSettingValue(value=default_value, source="default")

    def _secret_status(
        self,
        field_name: str,
        persisted_value: str | None,
    ) -> tuple[bool, SettingSource]:
        if field_name == "speech_api_key" and persisted_value is not None and persisted_value.strip():
            return True, "file"
        env_name = _FIELD_TO_ENV[field_name]
        direct_value = self.environment.get(env_name, "").strip()
        dashscope_value = self.environment.get("DASHSCOPE_API_KEY", "").strip()
        direct_is_process_owned = (
            bool(direct_value) and env_name not in self._injected_environment
        )
        if direct_is_process_owned or dashscope_value:
            return True, "environment"
        if persisted_value is not None and persisted_value.strip():
            return True, "file"
        return False, "default"

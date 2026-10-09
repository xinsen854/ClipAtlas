from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SettingSource = Literal["environment", "file", "default"]
JianyingModeSetting = Literal["portable", "jianying_pro_10_8"]


class PersistedSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    library_provider: str | None = None
    library_cache_root: str | None = None
    bailian_api_key: str | None = None
    bailian_base_url: str | None = None
    qwen_api_key: str | None = None
    qwen_base_url: str | None = None
    qwen_default_model: str | None = None
    qwen_long_context_model: str | None = None
    embedding_api_key: str | None = None
    embedding_base_url: str | None = None
    embedding_model: str | None = None
    embedding_dimensions: int | None = Field(default=None, gt=0)
    speech_provider: str | None = None
    speech_api_key: str | None = None
    speech_base_url: str | None = None
    speech_model: str | None = None
    jianying_draft_root: str | None = None
    jianying_install_dir: str | None = None
    jianying_user_data: str | None = None
    jianying_mode: JianyingModeSetting | None = None
    jianying_executable: str | None = None


class SettingsPatch(PersistedSettings):
    clear_bailian_api_key: bool = False
    clear_qwen_api_key: bool = False
    clear_embedding_api_key: bool = False
    clear_speech_api_key: bool = False


class PublicSettingValue(BaseModel):
    value: str | int | None
    source: SettingSource


class PublicSettings(BaseModel):
    library_provider: PublicSettingValue
    library_cache_root: PublicSettingValue
    bailian_base_url: PublicSettingValue
    qwen_base_url: PublicSettingValue
    qwen_default_model: PublicSettingValue
    qwen_long_context_model: PublicSettingValue
    embedding_base_url: PublicSettingValue
    embedding_model: PublicSettingValue
    embedding_dimensions: PublicSettingValue
    speech_provider: PublicSettingValue
    speech_base_url: PublicSettingValue
    speech_model: PublicSettingValue
    jianying_draft_root: PublicSettingValue
    jianying_install_dir: PublicSettingValue
    jianying_user_data: PublicSettingValue
    jianying_mode: PublicSettingValue
    jianying_executable: PublicSettingValue

    bailian_api_key_configured: bool
    bailian_api_key_source: SettingSource
    qwen_api_key_configured: bool
    qwen_api_key_source: SettingSource
    embedding_api_key_configured: bool
    embedding_api_key_source: SettingSource
    speech_api_key_configured: bool
    speech_api_key_source: SettingSource

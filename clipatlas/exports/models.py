from datetime import datetime
from enum import StrEnum
from pathlib import Path, PureWindowsPath
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from clipatlas.domain.models import utc_now

DEFAULT_JIANYING_DRAFT_ROOT = "./data/exports/jianying-drafts"


def validate_draft_name(value: str) -> str:
    if (
        not value.strip()
        or value.endswith((".", " "))
        or any(character in '<>:"/\\|?*' or ord(character) < 32 for character in value)
        or PureWindowsPath(value).is_reserved()
    ):
        raise ValueError("draft_name must be a valid Windows folder name, not a path")
    return value


def draft_name_from_script(script: str, *, max_length: int = 60) -> str:
    """First sentence of a narration script, cleaned into a Windows draft name.

    Cuts on the first sentence-ending punctuation, drops punctuation and
    whitespace runs, and truncates to a safe folder name length. Falls back to
    a generic name when the script has no usable sentence.
    """
    import re as _re

    text = (script or "").strip()
    first = _re.split(r"[。！？!?；;\n]+", text, maxsplit=1)[0].strip()
    cleaned = _re.sub(r"[^\w\u4e00-\u9fff-]+", "", first, flags=_re.UNICODE)
    cleaned = _re.sub(r"\s+", "", cleaned).strip(".- ")
    if not cleaned:
        cleaned = "ClipAtlas"
    return validate_draft_name(cleaned[:max_length])


def draft_name_from_cover(cover: str, *, max_length: int = 60) -> str:
    """Cover title line from a batch script, cleaned into a Windows draft name.

    Unlike draft_name_from_script this keeps the whole title (no sentence
    splitting): only Windows-illegal characters, line breaks and trailing
    punctuation are removed, so names like “L2.5、L2.9？强制性国标来了” stay
    recognisable.
    """
    import re as _re

    text = (cover or "").strip()
    cleaned = _re.sub(r"[\r\n]+", " ", text)
    cleaned = _re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "", cleaned)
    cleaned = _re.sub(r"\s+", " ", cleaned).strip(" .、，,;；:：!！")
    if not cleaned:
        return draft_name_from_script(cover, max_length=max_length)
    return validate_draft_name(cleaned[:max_length])


class OtioExportArtifact(BaseModel):
    plan_id: UUID
    project_id: UUID
    narration_track_id: UUID
    output_path: Path
    total_duration_ms: int = Field(gt=0)
    timing_rate: int = Field(gt=0)
    rough_cut_revision: int = Field(ge=1)
    narration_revision: int = Field(ge=1)
    created_at: datetime = Field(default_factory=utc_now)


class JianyingMode(StrEnum):
    PORTABLE = "portable"
    JIANYING_PRO_10_8 = "jianying_pro_10_8"


class JianyingExportSettings(BaseModel):
    draft_root: Path
    width: int = Field(default=1920, gt=0)
    height: int = Field(default=1080, gt=0)
    mode: JianyingMode = JianyingMode.PORTABLE
    install_dir: Path | None = None
    user_data_dir: Path | None = None
    # 封面标题（去标点后）用于成片片头标题卡；为空则不生成标题素材。
    cover_title: str | None = None

    @model_validator(mode="after")
    def validate_mode_paths(self) -> "JianyingExportSettings":
        if self.mode == JianyingMode.JIANYING_PRO_10_8:
            if self.install_dir is None:
                raise ValueError("install_dir is required for Jianying Pro 10.8 mode")
            if self.user_data_dir is None:
                raise ValueError("user_data_dir is required for Jianying Pro 10.8 mode")
        return self


class JianyingDraftArtifact(BaseModel):
    plan_id: UUID
    project_id: UUID
    narration_track_id: UUID
    draft_name: str = Field(min_length=1)
    output_path: Path
    mode: JianyingMode
    backend_name: str = Field(min_length=1)
    backend_version: str = Field(min_length=1)
    total_duration_ms: int = Field(gt=0)
    created_at: datetime = Field(default_factory=utc_now)

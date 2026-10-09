import os
from pathlib import Path
from typing import Protocol, cast
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, ValidationError, field_validator

from clipatlas.exports.errors import (
    JianyingConfigurationError,
    JianyingUnavailableError,
)
from clipatlas.exports.models import (
    DEFAULT_JIANYING_DRAFT_ROOT,
    JianyingDraftArtifact,
    JianyingExportSettings,
    JianyingMode,
    OtioExportArtifact,
    draft_name_from_cover,
    draft_name_from_script,
    validate_draft_name,
)
from clipatlas.speech.batches import export_ratio_resolution

router = APIRouter(prefix="/api/v1", tags=["exports"])


class ExportServiceLike(Protocol):
    def export_otio(self, plan_id: UUID) -> OtioExportArtifact: ...

    def export_jianying(
        self,
        plan_id: UUID,
        *,
        draft_name: str,
        settings: JianyingExportSettings,
    ) -> JianyingDraftArtifact: ...


class GeneratedArtifactRegistryLike(Protocol):
    def register_jianying(self, artifact: JianyingDraftArtifact) -> None: ...


class ExportOtioRequest(BaseModel):
    plan_id: UUID


class ExportJianyingRequest(BaseModel):
    plan_id: UUID
    draft_name: str | None = Field(default=None, min_length=1, max_length=200)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)

    @field_validator("draft_name")
    @classmethod
    def validate_draft_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_draft_name(value)


def _service(request: Request) -> ExportServiceLike:
    service = getattr(request.app.state, "export_service", None)
    if service is None or not hasattr(service, "export_otio") or not hasattr(service, "export_jianying"):
        raise JianyingUnavailableError("Timeline export service is not configured")
    return cast(ExportServiceLike, service)


def _resolve_export_options(
    request: Request,
    plan_id: UUID,
    body: ExportJianyingRequest,
) -> tuple[str, int, int, str | None]:
    """Resolve draft name, canvas size and cover title from the batch.

    The batch is the single source of truth for export ratio; the draft name is
    the first sentence of the narration script unless explicitly overridden.
    Falls back to the request body when the batch is unknown (e.g. standalone
    plans); the export service itself still validates plan existence.
    The cover title (封面标题/《》标题) also drives the on-screen title card.
    """
    rough_cut_store = getattr(request.app.state, "rough_cut_store", None)
    narration_store = getattr(request.app.state, "narration_store", None)
    plan = rough_cut_store.get_plan(plan_id) if rough_cut_store is not None else None

    entry_text: str | None = None
    entry_title: str | None = None
    export_ratio = "16:9"
    if plan is not None and narration_store is not None:
        for summary in narration_store.list_batches(plan.project_id, limit=100, offset=0):
            batch = narration_store.get_batch(summary.id)
            if batch is None:
                continue
            for entry in batch.entries:
                if entry.plan_id == plan_id:
                    entry_text = entry.text
                    entry_title = entry.title
                    export_ratio = batch.export_ratio or "16:9"
                    break
            if entry_text is not None:
                break

    width, height = export_ratio_resolution(export_ratio)
    if body.width is not None:
        width = body.width
    if body.height is not None:
        height = body.height

    cover_title: str | None = None
    if body.draft_name is not None:
        draft_name = body.draft_name
    elif entry_title:
        # 批量规则：草稿名优先取文案里的“封面标题”，
        # 没有封面标题行时回退到口播第一句。
        from clipatlas.speech.batches import extract_cover_title

        parsed_cover = extract_cover_title(entry_title)
        if parsed_cover:
            cover_title = parsed_cover
            try:
                draft_name = draft_name_from_cover(parsed_cover)
            except ValueError:
                draft_name = "ClipAtlas Rough Cut"
        else:
            try:
                draft_name = draft_name_from_script(entry_text or "")
            except ValueError:
                draft_name = "ClipAtlas Rough Cut"
    elif entry_text:
        try:
            draft_name = draft_name_from_script(entry_text)
        except ValueError:
            draft_name = "ClipAtlas Rough Cut"
    else:
        draft_name = "ClipAtlas Rough Cut"
    return draft_name, width, height, cover_title


def _register_jianying_artifact(
    request: Request,
    artifact: JianyingDraftArtifact,
) -> None:
    registry = getattr(request.app.state, "generated_artifact_registry", None)
    if registry is None:
        return
    if not hasattr(registry, "register_jianying"):
        raise TypeError("generated artifact registry is not configured")
    cast(GeneratedArtifactRegistryLike, registry).register_jianying(artifact)


def _jianying_settings(
    body: ExportJianyingRequest,
    *,
    width: int,
    height: int,
    cover_title: str | None = None,
) -> JianyingExportSettings:
    draft_root_raw = (
        os.getenv("CLIPATLAS_JIANYING_DRAFT_ROOT", "").strip()
        or DEFAULT_JIANYING_DRAFT_ROOT
    )

    mode_raw = os.getenv("CLIPATLAS_JIANYING_MODE", "portable").strip()
    try:
        mode = JianyingMode(mode_raw)
    except ValueError as exc:
        raise JianyingConfigurationError(f"Unsupported Jianying mode: {mode_raw}") from exc

    install_raw = os.getenv("CLIPATLAS_JIANYING_INSTALL_DIR", "").strip()
    user_data_raw = os.getenv("CLIPATLAS_JIANYING_USER_DATA", "").strip()
    try:
        return JianyingExportSettings(
            draft_root=Path(draft_root_raw),
            width=width,
            height=height,
            mode=mode,
            install_dir=Path(install_raw) if install_raw else None,
            user_data_dir=Path(user_data_raw) if user_data_raw else None,
            cover_title=cover_title,
        )
    except ValidationError as exc:
        raise JianyingConfigurationError("Jianying runtime configuration is incomplete") from exc


@router.post("/exports/otio", response_model=OtioExportArtifact)
def export_otio(request: Request, body: ExportOtioRequest) -> OtioExportArtifact:
    return _service(request).export_otio(body.plan_id)


@router.post("/exports/jianying", response_model=JianyingDraftArtifact)
def export_jianying(
    request: Request,
    body: ExportJianyingRequest,
) -> JianyingDraftArtifact:
    draft_name, width, height, cover_title = _resolve_export_options(request, body.plan_id, body)
    settings = _jianying_settings(body, width=width, height=height, cover_title=cover_title)
    artifact = _service(request).export_jianying(
        body.plan_id,
        draft_name=draft_name,
        settings=settings,
    )
    _register_jianying_artifact(request, artifact)
    return artifact

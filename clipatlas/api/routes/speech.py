from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging
from pathlib import Path
from typing import Annotated, Protocol, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field

from clipatlas.speech.contracts import SpeechProvider
from clipatlas.speech.errors import (
    SpeechConfigurationError,
    SpeechProfileNotFoundError,
    SpeechProviderUnavailableError,
)
from clipatlas.speech.models import (
    AgeStyle,
    NarrationSourceMode,
    NarrationTrack,
    NarrationUnit,
    NarrationWordTiming,
    ProjectScript,
    RandomMode,
    SpeechProfile,
    VoiceDescriptor,
    VoiceGender,
)
from clipatlas.speech.registry import SpeechProviderDescriptor, SpeechProviderRegistry
from clipatlas.speech.store import NarrationStore
from clipatlas.speech.voices import VoiceConstraints, VoiceSelector
from clipatlas.director.requirements import parse_script_visual_requirements

router = APIRouter(prefix="/api/v1", tags=["speech", "narration"])
logger = logging.getLogger(__name__)
_MAX_IMPORT_BYTES = 100 * 1024 * 1024


class NarrationServiceLike(Protocol):
    async def create_tts_track(
        self,
        project_id: UUID,
        script: str,
        profile: SpeechProfile,
    ) -> NarrationTrack: ...


class ImportedNarrationServiceLike(Protocol):
    def attach_script(self, track: NarrationTrack, script: str) -> NarrationTrack: ...

    async def import_track(
        self,
        project_id: UUID,
        source_path: Path,
        script: str,
        aligner: object | None = None,
        *,
        activate: bool = True,
        track_id: UUID | None = None,
    ) -> NarrationTrack: ...


class RandomizeProfileRequest(BaseModel):
    project_id: UUID
    provider: str
    mode: RandomMode = RandomMode.RANDOM_ALL
    seed: int
    constraints: VoiceConstraints = Field(default_factory=VoiceConstraints)
    voice_id: str | None = None


class CreateSpeechProfileRequest(BaseModel):
    project_id: UUID
    provider: str = Field(min_length=1)
    voice_id: str = Field(min_length=1)
    gender_constraint: VoiceGender | None = None
    age_style_constraint: AgeStyle | None = None
    language: str | None = None
    accent: str | None = None
    speed: float | None = Field(default=1.0, gt=0)
    pitch: float | None = None
    volume: float | None = None
    emotion: str | None = None
    style: str | None = None
    instruction: str | None = None
    locked: bool = False


class UpdateSpeechProfileRequest(BaseModel):
    provider: str | None = Field(default=None, min_length=1)
    voice_id: str | None = Field(default=None, min_length=1)
    gender_constraint: VoiceGender | None = None
    age_style_constraint: AgeStyle | None = None
    language: str | None = None
    accent: str | None = None
    speed: float | None = Field(default=None, gt=0)
    pitch: float | None = None
    volume: float | None = None
    emotion: str | None = None
    style: str | None = None
    instruction: str | None = None
    locked: bool | None = None


class CreateTtsTrackRequest(BaseModel):
    project_id: UUID
    script: str = Field(min_length=1)
    speech_profile_id: UUID


class NarrationTrackResponse(BaseModel):
    track: NarrationTrack
    units: list[NarrationUnit]
    word_timings: list[NarrationWordTiming]
    script: str = ""


class SaveProjectScriptRequest(BaseModel):
    text: str = Field(min_length=1, max_length=200000)
    attach_to_active_narration: bool = True


class SavedProjectScriptResponse(BaseModel):
    script: ProjectScript
    attached_track_id: UUID | None = None


class ProjectNarrationHistoryResponse(BaseModel):
    tracks: list[NarrationTrack]
    active_track_id: UUID | None = None


def _registry(request: Request) -> SpeechProviderRegistry:
    registry = getattr(request.app.state, "speech_registry", None)
    if not isinstance(registry, SpeechProviderRegistry):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="speech provider registry is not configured",
        )
    return registry


def _store(request: Request) -> NarrationStore:
    store = getattr(request.app.state, "narration_store", None)
    if not isinstance(store, NarrationStore):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="narration store is not configured",
        )
    return store


def _narration_service(request: Request) -> NarrationServiceLike:
    service = getattr(request.app.state, "narration_service", None)
    if service is None or not hasattr(service, "create_tts_track"):
        raise SpeechProviderUnavailableError("TTS narration is not configured")
    return cast(NarrationServiceLike, service)


def _imported_service(request: Request) -> ImportedNarrationServiceLike:
    service = getattr(request.app.state, "imported_narration_service", None)
    if service is None or not hasattr(service, "import_track"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="imported narration is not configured",
        )
    return cast(ImportedNarrationServiceLike, service)


def _track_response(store: NarrationStore, track: NarrationTrack) -> NarrationTrackResponse:
    units = store.list_units(track.id)
    return NarrationTrackResponse(
        track=track,
        units=units,
        word_timings=store.list_word_timings(track.id),
        script=track.script if track.script is not None else "\n".join(unit.text for unit in units),
    )


@router.get("/projects/{project_id}/script", response_model=ProjectScript)
def get_project_script(request: Request, project_id: UUID) -> ProjectScript:
    store = _store(request)
    saved = store.get_project_script(project_id)
    if saved is not None:
        return saved
    track = store.get_active_track(project_id)
    if track is None:
        return ProjectScript(project_id=project_id)
    return ProjectScript(
        project_id=project_id, text=_track_response(store, track).script,
        script_hash=track.script_hash,
    )


@router.put("/projects/{project_id}/script", response_model=SavedProjectScriptResponse)
async def save_project_script(
    request: Request, project_id: UUID, body: SaveProjectScriptRequest,
) -> SavedProjectScriptResponse:
    if not body.text.strip():
        raise HTTPException(status_code=422, detail="文案不能为空")
    if request.app.state.project_store.get(project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    store = _store(request)
    saved = store.save_project_script(project_id, body.text)
    track = store.get_active_track(project_id)
    attached = None
    if body.attach_to_active_narration and track is not None:
        if track.source_mode == NarrationSourceMode.IMPORTED:
            track = _imported_service(request).attach_script(track, body.text)
        if track.script_hash == saved.script_hash:
            attached = track.id
    query_service = getattr(request.app.state, "requirement_query_embedding_service", None)
    if query_service is not None:
        try:
            await query_service.prepare(parse_script_visual_requirements(saved.text))
        except Exception as exc:  # noqa: BLE001 - local fallback remains available
            logger.warning("script query-vector preparation unavailable: %s", str(exc)[:500])
    return SavedProjectScriptResponse(script=saved, attached_track_id=attached)


def _provider_or_404(request: Request, name: str) -> SpeechProvider:
    try:
        return _registry(request).get(name)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown speech provider: {name}",
        ) from exc


def _safe_upload_suffix(filename: str | None) -> str:
    suffix = Path(filename or "").suffix.lower()
    if 1 < len(suffix) <= 10 and suffix[1:].isalnum():
        return suffix
    return ".bin"


@router.get("/speech/providers", response_model=list[SpeechProviderDescriptor])
async def list_speech_providers(request: Request) -> list[SpeechProviderDescriptor]:
    return _registry(request).list_descriptors()


@router.get("/speech/providers/{provider}/voices", response_model=list[VoiceDescriptor])
async def list_speech_voices(request: Request, provider: str) -> list[VoiceDescriptor]:
    return await _provider_or_404(request, provider).list_voices()


@router.get("/projects/{project_id}/speech-profiles", response_model=list[SpeechProfile])
async def list_project_speech_profiles(request: Request, project_id: UUID) -> list[SpeechProfile]:
    return _store(request).list_profiles(project_id)


@router.get("/projects/{project_id}/narrations", response_model=ProjectNarrationHistoryResponse)
async def list_project_narrations(
    request: Request,
    project_id: UUID,
) -> ProjectNarrationHistoryResponse:
    store = _store(request)
    active_track = store.get_active_track(project_id)
    return ProjectNarrationHistoryResponse(
        tracks=store.list_tracks(project_id),
        active_track_id=active_track.id if active_track is not None else None,
    )


@router.post("/speech/profiles", response_model=SpeechProfile)
async def create_speech_profile(
    request: Request,
    body: CreateSpeechProfileRequest,
) -> SpeechProfile:
    provider = _provider_or_404(request, body.provider)
    profile = SpeechProfile(
        project_id=body.project_id,
        provider=provider.name,
        model=provider.model,
        voice_id=body.voice_id,
        gender_constraint=body.gender_constraint,
        age_style_constraint=body.age_style_constraint,
        language=body.language,
        accent=body.accent,
        speed=body.speed,
        pitch=body.pitch,
        volume=body.volume,
        emotion=body.emotion,
        style=body.style,
        instruction=body.instruction,
        random_mode=RandomMode.NONE,
        locked=body.locked,
    )
    _store(request).save_profile(profile)
    return profile


@router.patch("/speech/profiles/{profile_id}", response_model=SpeechProfile)
async def update_speech_profile(
    request: Request,
    profile_id: UUID,
    body: UpdateSpeechProfileRequest,
) -> SpeechProfile:
    store = _store(request)
    current = store.get_profile(profile_id)
    if current is None:
        raise SpeechProfileNotFoundError("speech profile not found")

    changes = body.model_dump(exclude_unset=True)
    provider_name = changes.pop("provider", None)
    if provider_name is not None:
        provider = _provider_or_404(request, provider_name)
        changes["provider"] = provider.name
        changes["model"] = provider.model

    profile_data = current.model_dump(exclude={"id", "created_at", "revision"})
    profile_data.update(changes)
    revised = SpeechProfile(
        **profile_data,
        id=uuid4(),
        revision=current.revision + 1,
    )
    store.save_profile(revised)
    return revised


@router.post("/speech/profiles/randomize", response_model=SpeechProfile)
async def randomize_speech_profile(
    request: Request,
    body: RandomizeProfileRequest,
) -> SpeechProfile:
    provider = _provider_or_404(request, body.provider)
    voices = await provider.list_voices()
    profile = VoiceSelector().select(
        project_id=body.project_id,
        provider=provider.name,
        model=provider.model,
        voices=voices,
        constraints=body.constraints,
        mode=body.mode,
        seed=body.seed,
        capabilities=provider.capabilities,
        voice_id=body.voice_id,
    )
    _store(request).save_profile(profile)
    return profile


@router.post("/narration/tts", response_model=NarrationTrackResponse)
async def create_tts_narration(
    request: Request,
    body: CreateTtsTrackRequest,
) -> NarrationTrackResponse:
    store = _store(request)
    profile = store.get_profile(body.speech_profile_id)
    if profile is None:
        raise SpeechProfileNotFoundError("speech profile not found")
    if profile.project_id != body.project_id:
        raise SpeechConfigurationError("speech profile belongs to another project")
    track = await _narration_service(request).create_tts_track(
        body.project_id,
        body.script,
        profile,
    )
    store.save_project_script(body.project_id, body.script)
    return _track_response(store, track)


@asynccontextmanager
async def _uploaded_audio(request: Request, file: UploadFile) -> AsyncIterator[Path]:
    root_value = getattr(request.app.state, "narration_root", None)
    if root_value is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="narration root is not configured",
        )
    root = Path(root_value).resolve()
    upload_root = root / ".uploads"
    upload_root.mkdir(parents=True, exist_ok=True)
    temp_path = upload_root / f"{uuid4().hex}{_safe_upload_suffix(file.filename)}"

    data = await file.read(_MAX_IMPORT_BYTES + 1)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="uploaded narration is empty",
        )
    if len(data) > _MAX_IMPORT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="uploaded narration exceeds maximum size",
        )

    temp_path.write_bytes(data)
    try:
        yield temp_path
    finally:
        temp_path.unlink(missing_ok=True)


@router.post("/narration/import", response_model=NarrationTrackResponse)
async def import_narration(
    request: Request,
    project_id: Annotated[UUID, Form()],
    script: Annotated[str, Form(min_length=1)],
    file: Annotated[UploadFile, File()],
) -> NarrationTrackResponse:
    async with _uploaded_audio(request, file) as temp_path:
        track = await _imported_service(request).import_track(
            project_id,
            temp_path,
            script,
        )
    _store(request).save_project_script(project_id, script)
    return _track_response(_store(request), track)


@router.get("/narration/{track_id}", response_model=NarrationTrackResponse)
async def get_narration_track(request: Request, track_id: UUID) -> NarrationTrackResponse:
    store = _store(request)
    track = store.get_track(track_id)
    if track is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="narration track not found",
        )
    return _track_response(store, track)


@router.post("/narration/{track_id}/activate", response_model=NarrationTrackResponse)
async def activate_narration_track(request: Request, track_id: UUID) -> NarrationTrackResponse:
    store = _store(request)
    track = store.get_track(track_id)
    if track is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="narration track not found",
        )
    if not store.activate_track(track.project_id, track.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="failed to activate narration track",
        )
    store.save_project_script(track.project_id, _track_response(store, track).script)
    return _track_response(store, track)

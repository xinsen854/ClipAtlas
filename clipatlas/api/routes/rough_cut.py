from typing import Literal, Protocol, cast
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, model_validator

from clipatlas.director.story_errors import AutoDirectorUnavailableError
from clipatlas.director.story_models import StoryOutline
from clipatlas.director.story_service import StoryDirectorService
from clipatlas.roughcut.errors import (
    RoughCutPlanNotFoundError,
    RoughCutUnavailableError,
)
from clipatlas.roughcut.models import RoughCutPlan
from clipatlas.roughcut.store import RoughCutStore
from clipatlas.speech.models import NarrationTrack

router = APIRouter(prefix="/api/v1", tags=["rough-cut"])


class RoughCutPlannerLike(Protocol):
    async def create_plan(
        self,
        project_id: UUID,
        *,
        top_k: int = 12,
        video_ids: list[UUID] | None = None,
        narration_track_id: UUID | None = None,
        script_text: str | None = None,
        activate: bool = True,
        plan_id: UUID | None = None,
        persist: bool = True,
        batch_usage: dict[str, list[tuple[int, int, int]]] | None = None,
        batch_index: int = 0,
        story_outline: StoryOutline | None = None,
        story_node_narration_unit_ids: dict[UUID, list[UUID]] | None = None,
    ) -> RoughCutPlan: ...


class OriginalAudioNarrationLike(Protocol):
    async def prepare(
        self,
        project_id: UUID,
        outline: StoryOutline,
    ) -> tuple[NarrationTrack, dict[UUID, list[UUID]]]: ...


class StoryTtsNarrationLike(Protocol):
    async def prepare(
        self,
        project_id: UUID,
        outline: StoryOutline,
        speech_profile_id: UUID,
    ) -> tuple[NarrationTrack, dict[UUID, list[UUID]]]: ...


class CreateRoughCutPlanRequest(BaseModel):
    project_id: UUID
    top_k: int = Field(default=12, ge=1, le=100)
    video_ids: list[UUID] | None = None
    narration_track_id: UUID | None = None
    story_outline_id: UUID | None = None
    story_node_narration_unit_ids: dict[UUID, list[UUID]] | None = None
    voice_strategy: Literal["original_audio", "tts"] | None = None
    speech_profile_id: UUID | None = None

    @model_validator(mode="after")
    def validate_story_handoff(self) -> "CreateRoughCutPlanRequest":
        if self.story_outline_id is None:
            if any((
                self.story_node_narration_unit_ids is not None,
                self.voice_strategy is not None,
                self.speech_profile_id is not None,
            )):
                raise ValueError("Story execution requires story_outline_id")
            return self
        if self.voice_strategy in {"original_audio", "tts"}:
            if self.story_node_narration_unit_ids is not None or self.narration_track_id is not None:
                raise ValueError(
                    f"{self.voice_strategy} prepares its narration track and node mapping"
                )
            if self.voice_strategy == "tts" and self.speech_profile_id is None:
                raise ValueError("tts requires speech_profile_id")
            if self.voice_strategy == "original_audio" and self.speech_profile_id is not None:
                raise ValueError("original_audio does not use speech_profile_id")
        elif self.story_node_narration_unit_ids is None:
            raise ValueError(
                "Story execution requires story_node_narration_unit_ids"
            )
        elif self.speech_profile_id is not None:
            raise ValueError("speech_profile_id requires tts voice strategy")
        return self


def _planner(request: Request) -> RoughCutPlannerLike:
    planner = getattr(request.app.state, "rough_cut_planner", None)
    if planner is None or not hasattr(planner, "create_plan"):
        raise RoughCutUnavailableError(
            "Automatic rough-cut planning is not configured"
        )
    return cast(RoughCutPlannerLike, planner)


def _store(request: Request) -> RoughCutStore:
    store = getattr(request.app.state, "rough_cut_store", None)
    if not isinstance(store, RoughCutStore):
        raise RoughCutUnavailableError("Rough-cut store is not configured")
    return store


def _story_service(request: Request) -> StoryDirectorService:
    service = getattr(request.app.state, "story_director_service", None)
    if not isinstance(service, StoryDirectorService):
        raise AutoDirectorUnavailableError("自动编导服务未配置")
    return service


def _original_audio_narration(request: Request) -> OriginalAudioNarrationLike:
    adapter = getattr(request.app.state, "original_audio_narration", None)
    if adapter is None or not hasattr(adapter, "prepare"):
        raise RoughCutUnavailableError("Original audio narration is not configured")
    return cast(OriginalAudioNarrationLike, adapter)


def _story_tts_narration(request: Request) -> StoryTtsNarrationLike:
    adapter = getattr(request.app.state, "story_tts_narration", None)
    if adapter is None or not hasattr(adapter, "prepare"):
        raise RoughCutUnavailableError("Story TTS narration is not configured")
    return cast(StoryTtsNarrationLike, adapter)


@router.post("/rough-cut/plans", response_model=RoughCutPlan)
async def create_rough_cut_plan(
    request: Request,
    body: CreateRoughCutPlanRequest,
) -> RoughCutPlan:
    planner = _planner(request)
    if body.story_outline_id is not None:
        outline = _story_service(request).get_confirmed(
            body.project_id,
            body.story_outline_id,
        )
        narration_track_id = body.narration_track_id
        node_mapping = body.story_node_narration_unit_ids
        if body.voice_strategy == "original_audio":
            track, node_mapping = await _original_audio_narration(request).prepare(
                body.project_id,
                outline,
            )
            narration_track_id = track.id
        elif body.voice_strategy == "tts":
            assert body.speech_profile_id is not None
            track, node_mapping = await _story_tts_narration(request).prepare(
                body.project_id,
                outline,
                body.speech_profile_id,
            )
            narration_track_id = track.id
        assert node_mapping is not None
        return await planner.create_plan(
            body.project_id,
            top_k=body.top_k,
            video_ids=body.video_ids,
            narration_track_id=narration_track_id,
            story_outline=outline,
            story_node_narration_unit_ids=node_mapping,
        )
    if body.narration_track_id is not None:
        return await planner.create_plan(
            body.project_id,
            top_k=body.top_k,
            video_ids=body.video_ids,
            narration_track_id=body.narration_track_id,
        )
    return await planner.create_plan(
        body.project_id,
        top_k=body.top_k,
        video_ids=body.video_ids,
    )


@router.get("/projects/{project_id}/rough-cut/plans", response_model=list[RoughCutPlan])
async def list_project_rough_cut_plans(
    request: Request,
    project_id: UUID,
) -> list[RoughCutPlan]:
    return _store(request).list_plans(project_id)


@router.get("/rough-cut/plans/active", response_model=RoughCutPlan)
async def get_active_rough_cut_plan(
    request: Request,
    project_id: UUID,
) -> RoughCutPlan:
    plan = _store(request).get_active_plan(project_id)
    if plan is None:
        raise RoughCutPlanNotFoundError(
            f"No active rough-cut plan for project {project_id}"
        )
    return plan


@router.get("/rough-cut/plans/{plan_id}", response_model=RoughCutPlan)
async def get_rough_cut_plan(request: Request, plan_id: UUID) -> RoughCutPlan:
    plan = _store(request).get_plan(plan_id)
    if plan is None:
        raise RoughCutPlanNotFoundError(f"Rough-cut plan {plan_id} not found")
    return plan

from typing import cast
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from clipatlas.director.story_errors import AutoDirectorUnavailableError
from clipatlas.director.story_models import StoryOutline, StoryOutlineEditNode, StoryReadiness
from clipatlas.director.story_service import StoryDirectorService

router = APIRouter(prefix="/api/v1", tags=["auto-director"])


class AnalyzeStoryRequest(BaseModel):
    project_id: UUID
    skill_name: str = Field(min_length=1, max_length=200)
    skill_content: str = Field(min_length=1, max_length=200_000)


class EditStoryOutlineRequest(BaseModel):
    project_id: UUID
    summary: str = Field(min_length=1, max_length=20_000)
    hook_rationale: str = Field(default="", max_length=8_000)
    nodes: list[StoryOutlineEditNode] = Field(min_length=1)


class ConfirmStoryOutlineRequest(BaseModel):
    project_id: UUID


def _service(request: Request) -> StoryDirectorService:
    service = getattr(request.app.state, "story_director_service", None)
    if not isinstance(service, StoryDirectorService):
        raise AutoDirectorUnavailableError("自动编导尚未配置模型 API")
    return cast(StoryDirectorService, service)


@router.get(
    "/projects/{project_id}/auto-director/readiness",
    response_model=StoryReadiness,
)
def get_story_readiness(request: Request, project_id: UUID) -> StoryReadiness:
    return _service(request).readiness(project_id)


@router.post("/auto-director/analyze", response_model=StoryOutline)
async def analyze_story(request: Request, body: AnalyzeStoryRequest) -> StoryOutline:
    return await _service(request).analyze(
        body.project_id,
        skill_name=body.skill_name,
        skill_content=body.skill_content,
    )


@router.get(
    "/projects/{project_id}/auto-director/outlines",
    response_model=list[StoryOutline],
)
def list_story_outlines(request: Request, project_id: UUID) -> list[StoryOutline]:
    return _service(request).list_project(project_id)


@router.put("/auto-director/outlines/{outline_id}", response_model=StoryOutline)
def edit_story_outline(
    request: Request,
    outline_id: UUID,
    body: EditStoryOutlineRequest,
) -> StoryOutline:
    return _service(request).edit(
        body.project_id,
        outline_id,
        summary=body.summary,
        hook_rationale=body.hook_rationale,
        nodes=body.nodes,
    )


@router.post("/auto-director/outlines/{outline_id}/confirm", response_model=StoryOutline)
def confirm_story_outline(
    request: Request,
    outline_id: UUID,
    body: ConfirmStoryOutlineRequest,
) -> StoryOutline:
    return _service(request).confirm(body.project_id, outline_id)

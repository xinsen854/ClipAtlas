import asyncio
import sqlite3
from typing import Literal, cast
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from clipatlas.concurrency import drain_on_cancel
from clipatlas.projects.maintenance import (
    ProjectDeletionPreview,
    ProjectDeletionResult,
    ProjectMaintenance,
)
from clipatlas.projects.models import Project
from clipatlas.projects.store import ProjectStore

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class UpdateProjectRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class DeleteProjectRequest(BaseModel):
    confirm: Literal['DELETE_PROJECT']


def _store(request: Request) -> ProjectStore:
    store = getattr(request.app.state, "project_store", None)
    if not isinstance(store, ProjectStore):
        raise TypeError("project store is not configured")
    return store


def _project_or_404(store: ProjectStore, project_id: UUID) -> Project:
    project = store.get(project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="project not found",
        )
    return project


@router.post("", response_model=Project, status_code=status.HTTP_201_CREATED)
def create_project(request: Request, body: CreateProjectRequest) -> Project:
    return _store(request).create(body.name, body.description)


@router.get("", response_model=list[Project])
def list_projects(request: Request) -> list[Project]:
    return _store(request).list_projects()


@router.get("/{project_id}", response_model=Project)
def get_project(request: Request, project_id: UUID) -> Project:
    return _project_or_404(_store(request), project_id)


@router.patch("/{project_id}", response_model=Project)
def update_project(
    request: Request,
    project_id: UUID,
    body: UpdateProjectRequest,
) -> Project:
    project = _store(request).update(
        project_id,
        name=body.name,
        description=body.description,
        description_set="description" in body.model_fields_set,
    )
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="project not found",
        )
    return project


@router.get('/{project_id}/deletion-preview', response_model=ProjectDeletionPreview)
def deletion_preview(request: Request, project_id: UUID) -> ProjectDeletionPreview:
    _project_or_404(_store(request), project_id)
    maintenance = cast(ProjectMaintenance, request.app.state.project_maintenance)
    try:
        return maintenance.preview(project_id)
    except (ValueError, OSError, sqlite3.Error) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete('/{project_id}', response_model=ProjectDeletionResult)
async def delete_project(request: Request, project_id: UUID, body: DeleteProjectRequest) -> ProjectDeletionResult:
    _project_or_404(_store(request), project_id)
    maintenance = cast(ProjectMaintenance, request.app.state.project_maintenance)

    async def remove() -> ProjectDeletionResult:
        result = await asyncio.to_thread(maintenance.delete, project_id)
        registry = getattr(request.app.state, 'generated_artifact_registry', None)
        if registry is not None:
            for plan_id in result.plan_ids:
                registry.discard(plan_id)
        return result

    try:
        return await drain_on_cancel(remove())
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, OSError, sqlite3.Error) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

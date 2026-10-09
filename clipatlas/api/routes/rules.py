from typing import Protocol
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from clipatlas.projects.store import ProjectStore
from clipatlas.rules.analyzer import RuleAnalysisResult
from clipatlas.rules.models import (
    ProjectRule,
    ProjectRulePack,
    ProjectedText,
    RulePackStatus,
)
from clipatlas.rules.projector import ProjectTextProjector
from clipatlas.rules.store import ProjectRuleStore

router = APIRouter(prefix="/api/v1/projects/{project_id}/rules", tags=["rules"])


class RuleAnalyzerLike(Protocol):
    async def analyze(self, source_text: str) -> RuleAnalysisResult: ...


class SaveRuleDraftRequest(BaseModel):
    rules: list[ProjectRule] = Field(default_factory=list)


class PreviewRulesRequest(BaseModel):
    text: str
    rules: list[ProjectRule] = Field(default_factory=list)


class AnalyzeRulesRequest(BaseModel):
    text: str


def _project_store(request: Request) -> ProjectStore:
    store = getattr(request.app.state, "project_store", None)
    if not isinstance(store, ProjectStore):
        raise TypeError("project store is not configured")
    return store


def _rule_store(request: Request) -> ProjectRuleStore:
    store = getattr(request.app.state, "project_rule_store", None)
    if not isinstance(store, ProjectRuleStore):
        raise TypeError("project rule store is not configured")
    return store


def _ensure_project(request: Request, project_id: UUID) -> None:
    if _project_store(request).get(project_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="project not found",
        )


@router.post("/drafts", response_model=ProjectRulePack, status_code=status.HTTP_201_CREATED)
def save_rule_draft(
    request: Request,
    project_id: UUID,
    body: SaveRuleDraftRequest,
) -> ProjectRulePack:
    _ensure_project(request, project_id)
    return _rule_store(request).save_draft(project_id, body.rules)


@router.get("", response_model=list[ProjectRulePack])
def list_rule_revisions(request: Request, project_id: UUID) -> list[ProjectRulePack]:
    _ensure_project(request, project_id)
    return _rule_store(request).list_revisions(project_id)


@router.get("/active", response_model=ProjectRulePack)
def get_active_rule_pack(request: Request, project_id: UUID) -> ProjectRulePack:
    _ensure_project(request, project_id)
    pack = _rule_store(request).get_active(project_id)
    if pack is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="active project rule pack not found",
        )
    return pack


@router.post("/{revision}/activate", response_model=ProjectRulePack)
def activate_rule_pack(
    request: Request,
    project_id: UUID,
    revision: int,
) -> ProjectRulePack:
    _ensure_project(request, project_id)
    pack = _rule_store(request).activate(project_id, revision)
    if pack is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="project rule revision not found",
        )
    return pack


@router.post("/preview", response_model=ProjectedText)
def preview_rules(
    request: Request,
    project_id: UUID,
    body: PreviewRulesRequest,
) -> ProjectedText:
    _ensure_project(request, project_id)
    pack = ProjectRulePack(
        project_id=project_id,
        revision=1,
        status=RulePackStatus.DRAFT,
        rules=body.rules,
    )
    return ProjectTextProjector().project(body.text, pack)


@router.post("/analyze", response_model=RuleAnalysisResult)
async def analyze_rules(
    request: Request,
    project_id: UUID,
    body: AnalyzeRulesRequest,
) -> RuleAnalysisResult:
    _ensure_project(request, project_id)
    analyzer = getattr(request.app.state, "project_rule_analyzer", None)
    if analyzer is None or not callable(getattr(analyzer, "analyze", None)):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="project rule analyzer is not configured",
        )
    return await analyzer.analyze(body.text)

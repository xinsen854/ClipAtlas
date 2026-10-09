from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator

from clipatlas.domain.models import utc_now

StoryRole = Literal[
    "hook",
    "setup",
    "development",
    "reversal",
    "payoff",
    "ending",
    "other",
]
StoryEvidenceKind = Literal["visual", "asr", "ocr"]
StoryOutlineStatus = Literal["draft", "confirmed"]


class StorySkill(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=200_000)

    @property
    def content_hash(self) -> str:
        return sha256(self.content.encode("utf-8")).hexdigest()


class StoryEvidenceItem(BaseModel):
    evidence_id: str = Field(min_length=1)
    kind: StoryEvidenceKind
    video_id: UUID
    segment_id: UUID | None = None
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    text: str = Field(min_length=1)
    source_name: str = ""

    @model_validator(mode="after")
    def validate_range(self) -> "StoryEvidenceItem":
        if self.end_ms <= self.start_ms:
            raise ValueError("story evidence end_ms must be greater than start_ms")
        return self


class StoryEvidencePacket(BaseModel):
    project_id: UUID
    video_count: int = Field(ge=0)
    items: list[StoryEvidenceItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class StoryReadiness(BaseModel):
    project_id: UUID
    ready: bool
    video_count: int = Field(default=0, ge=0)
    evidence_count: int = Field(default=0, ge=0)
    visual_count: int = Field(default=0, ge=0)
    asr_count: int = Field(default=0, ge=0)
    ocr_count: int = Field(default=0, ge=0)
    warnings: list[str] = Field(default_factory=list)
    message: str = ""


class StoryEvidenceReference(BaseModel):
    evidence_id: str = Field(min_length=1)
    kind: StoryEvidenceKind
    video_id: UUID
    segment_id: UUID | None = None
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    text: str = Field(min_length=1)
    source_name: str = ""


class StoryNodeDraft(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    summary: str = Field(min_length=1, max_length=4_000)
    role: StoryRole = "other"
    estimated_duration_ms: int = Field(default=3_000, gt=0, le=600_000)
    evidence_ids: list[str] = Field(min_length=1)


class StoryAnalysisResult(BaseModel):
    summary: str = Field(min_length=1, max_length=20_000)
    hook_rationale: str = Field(default="", max_length=8_000)
    nodes: list[StoryNodeDraft] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)


class StoryOutlineNode(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    order: int = Field(ge=0)
    title: str = Field(min_length=1, max_length=300)
    summary: str = Field(min_length=1, max_length=4_000)
    role: StoryRole = "other"
    estimated_duration_ms: int = Field(default=3_000, gt=0, le=600_000)
    evidence: list[StoryEvidenceReference] = Field(min_length=1)


class StoryOutline(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    revision: int = Field(ge=1)
    skill_name: str = Field(min_length=1, max_length=200)
    skill_hash: str = Field(min_length=64, max_length=64)
    summary: str = Field(min_length=1, max_length=20_000)
    hook_rationale: str = Field(default="", max_length=8_000)
    nodes: list[StoryOutlineNode] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)
    status: StoryOutlineStatus = "draft"
    created_at: datetime = Field(default_factory=utc_now)
    confirmed_at: datetime | None = None


class StoryOutlineEditNode(BaseModel):
    id: UUID
    title: str = Field(min_length=1, max_length=300)
    summary: str = Field(min_length=1, max_length=4_000)
    role: StoryRole = "other"
    estimated_duration_ms: int = Field(default=3_000, gt=0, le=600_000)

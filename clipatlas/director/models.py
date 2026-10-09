"""Director-layer models: S/A/B script grading units for rough-cut planning.

The director layer runs once per finalised script (one API call, permanently
cached) and decides what the narration *means*, so the local retrieval layer
can judge whether a candidate frame is DIRECT / SUPPORT / REJECT without any
per-candidate API call.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from clipatlas.domain.models import utc_now
from clipatlas.domain.evidence import VisualClaim
from clipatlas.domain.visual_protocol import ScriptVisualRequirement

Importance = Literal["S", "A", "B"]


class DirectorUnit(BaseModel):
    """One content unit with a director-level visual requirement."""

    text_range: str = Field(min_length=1)
    importance: Importance
    topic: str = Field(min_length=1)
    subtopics: list[str] = Field(default_factory=list)
    required_subjects: list[str] = Field(default_factory=list)
    required_objects: list[str] = Field(default_factory=list)
    required_actions: list[str] = Field(default_factory=list)
    acceptable_surrogates: list[str] = Field(default_factory=list)
    must_have: list[str] = Field(default_factory=list)
    preferred: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    visual_function: str = ""
    anchor_phrase: str = ""
    claims: list[VisualClaim] = Field(default_factory=list)
    visual_goal: Literal["proof", "related", "continuity"] | None = None
    contract_issues: list[str] = Field(default_factory=list)
    # Filled locally after narration alignment: inclusive range of beat
    # sequence indexes whose spoken text this unit covers.
    beat_range: tuple[int, int] | None = None

    @model_validator(mode="after")
    def require_some_requirement(self) -> "DirectorUnit":
        if not (
            self.required_subjects
            or self.required_objects
            or self.required_actions
            or self.acceptable_surrogates
            or self.must_have
            or self.preferred
            or self.claims
            or self.visual_goal in {"related", "continuity"}
        ):
            if self.importance in {"S", "A"}:
                raise ValueError(
                    "S/A units must carry required subjects, objects, actions or surrogates"
                )
        return self


class DirectorAnalysis(BaseModel):
    script_text: str
    script_hash: str
    prompt_version: str
    rules_revision: str
    # Payloads created before visual-retrieval-v2 load as legacy explicitly.
    protocol_version: str = "legacy-director-v4"
    units: list[DirectorUnit] = Field(default_factory=list)
    requirements: list[ScriptVisualRequirement] = Field(default_factory=list)
    api_request_count: int = Field(default=0, ge=0)
    cache_hit: bool = False
    status: Literal["ready", "failed", "legacy"] = "ready"
    contract_issues: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)

    def units_by_importance(self, importance: Importance) -> list[DirectorUnit]:
        return [unit for unit in self.units if unit.importance == importance]

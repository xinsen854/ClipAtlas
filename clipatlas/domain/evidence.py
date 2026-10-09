"""Versioned vocabulary shared by ingest evidence and narration requirements."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Predicate = Literal["identity", "presence", "action", "configuration", "scene", "quantity", "relation"]
EvidenceKind = Literal["visual", "source_text", "diagram", "source_audio"]


class Proposition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: str = Field(min_length=1)
    predicate: Predicate
    value: str = Field(min_length=1)
    unit: str | None = None
    scope: str | None = None
    polarity: Literal["positive", "negative"] = "positive"

    @model_validator(mode="after")
    def quantity_has_context(self) -> "Proposition":
        if self.predicate == "quantity" and (not self.unit or not self.scope):
            raise ValueError("quantity requires a unit and semantic scope")
        return self


class EvidenceStatement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposition: Proposition
    entity_id: str = Field(min_length=1)
    kind: EvidenceKind
    representation: Literal["real_scene", "screen", "diagram", "cg", "title_card", "audio"]
    frame_ids: list[str] = Field(default_factory=list)
    temporal_basis: Literal["point", "interval", "unknown"] = "unknown"

    @model_validator(mode="after")
    def evidence_medium(self) -> "EvidenceStatement":
        if self.kind == "visual" and self.representation not in {"real_scene", "screen"}:
            raise ValueError("visual evidence must be a filmed scene or filmed screen")
        if self.proposition.predicate == "action" and self.kind == "visual":
            if self.temporal_basis != "interval" or len(set(self.frame_ids)) < 2:
                raise ValueError("observed action requires an interval and multiple observed frames")
        return self


class EvidenceAlternative(BaseModel):
    model_config = ConfigDict(extra="forbid")
    all_of: list[Proposition] = Field(min_length=1, max_length=8)
    allowed_kinds: list[EvidenceKind] = Field(min_length=1)
    same_entity: bool = True
    simultaneous: bool = False


class VisualClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim_id: str = Field(min_length=1)
    source_quote: str = Field(min_length=1)
    goal: Literal["proof", "related"] = "proof"
    any_of: list[EvidenceAlternative] = Field(min_length=1, max_length=4)


class ClaimMatch(BaseModel):
    claim_id: str
    source_quote: str
    importance: Literal["S", "A", "B"]
    goal: Literal["proof", "related"]
    level: Literal["DIRECT", "SUPPORT", "UNKNOWN", "REJECT"]
    evidence_ids: list[str] = Field(default_factory=list)
    evidence_kinds: list[EvidenceKind] = Field(default_factory=list)
    source_ranges: list[tuple[int, int]] = Field(default_factory=list)
    matched_conditions: list[str] = Field(default_factory=list)
    missing_conditions: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


CONTRACT_VERSION = "visual-evidence-v1"
PROPOSITION_INSTRUCTIONS = """
Use the shared visual-evidence-v1 contract. A proposition is
{subject: canonical entity/model name, predicate: identity|presence|action|configuration|scene|quantity|relation,
 value: one atomic concept, unit: null|string, scope: null|string, polarity: positive|negative}.
Bind quantity to its unit AND meaning (e.g. 1500, 场/年, 线下活动), not a bare number.
Keep brand, model and variant distinct; 泰钽700 is NOT 坦克700/Tank 700. Do not guess identity.
Use Chinese atomic concepts, preserving actual model/version text. Do not conflate lidar/radar,
driving/parking, aerial viewpoint/drone object, equipment presence/equipment operation.
"""

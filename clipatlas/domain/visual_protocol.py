"""Versioned visual evidence protocol used by ingest, retrieval and planning.

The protocol is intentionally additive.  Legacy annotations and semantic spans
remain readable, while new event/window records carry enough structure for
conservative temporal matching.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator

from clipatlas.domain.models import utc_now


PROTOCOL_VERSION = "visual-retrieval-v2"
ContinuityStatus = Literal[
    "confirmed_continuity", "probable_continuity", "unknown_continuity"
]
Importance = Literal["S", "A", "B"]
MatchLevel = Literal["DIRECT", "SUPPORT", "RELATED", "GENERIC"]


def normalize_match_level(schedule_level: str | None, director_level: str | None = None) -> MatchLevel:
    """Normalize legacy scheduler levels into the four public match levels."""
    if director_level == "DIRECT" or schedule_level == "exact":
        return "DIRECT"
    if director_level == "SUPPORT" or schedule_level == "related":
        return "SUPPORT"
    if schedule_level in {"generic", "c_tail"}:
        return "GENERIC"
    return "RELATED"


class EvidenceRef(BaseModel):
    segment_id: UUID | None = None
    frame_ids: list[str] = Field(default_factory=list)
    source: Literal["visual", "source_text", "diagram", "source_audio", "ocr", "legacy"] = "visual"
    time_basis: Literal["point", "interval", "unknown"] = "unknown"
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @property
    def evidence_kind(self) -> str:
        return self.source

    @property
    def temporal_basis(self) -> str:
        return self.time_basis


class VideoTimelineEvent(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    # Canonical protocol names. ``id`` and the evidence_* fields remain as
    # compatibility aliases for older catalog rows and callers.
    event_id: UUID | None = None
    video_id: UUID
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    subject_name: str | None = None
    entity_name: str | None = None
    entity_id: str | None = None
    entity_track_id: str | None = None
    entity_type: str | None = None
    vehicle_model: str | None = None
    brand: str | None = None
    version: str | None = None
    variant: str | None = None
    action: str | None = None
    action_phase: str | None = None
    motion_direction: str | None = None
    action_intensity: str | None = None
    scene: str | None = None
    road_type: str | None = None
    road_surface: str | None = None
    environment: str | None = None
    location_type: str | None = None
    weather: str | None = None
    indoor_outdoor: Literal["indoor", "outdoor", "unknown"] = "unknown"
    objects: list[str] = Field(default_factory=list)
    configurations: list[str] = Field(default_factory=list)
    visible_equipment: list[str] = Field(default_factory=list)
    ocr: list[str] = Field(default_factory=list)
    quantities: list[str] = Field(default_factory=list)
    relations: list[str] = Field(default_factory=list)
    state_before: str | None = None
    state_after: str | None = None
    state_changes: list[str] = Field(default_factory=list)
    shot_scale: str | None = None
    shot_type: str | None = None
    camera_position: str | None = None
    viewpoint: str | None = None
    camera_viewpoint: str | None = None
    camera_height: str | None = None
    camera_direction: str | None = None
    aerial_view: bool | None = None
    camera_motion: str | None = None
    interior_exterior: str | None = None
    interior_or_exterior: str | None = None
    same_subject_as_previous: bool | None = None
    same_entity_as_previous: bool | None = None
    same_scene_as_previous: bool | None = None
    continuous_motion: bool | None = None
    transition_type: str | None = None
    continuity_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    evidence_segment_ids: list[UUID] = Field(default_factory=list)
    evidence_frame_ids: list[str] = Field(default_factory=list)
    segment_ids: list[UUID] = Field(default_factory=list)
    frame_ids: list[str] = Field(default_factory=list)
    evidence_kind: str | None = None
    time_basis: Literal["observed_interval", "segment_range", "unknown"] = "unknown"
    temporal_basis: Literal["point", "interval", "unknown"] = "unknown"
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    unknown_fields: list[str] = Field(default_factory=list)
    unknown_conditions: list[str] = Field(default_factory=list)
    protocol_version: str = PROTOCOL_VERSION
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_range(self) -> "VideoTimelineEvent":
        if self.end_ms <= self.start_ms:
            raise ValueError("event end_ms must be greater than start_ms")
        if self.event_id is None:
            self.event_id = self.id
        else:
            self.id = self.event_id
        if self.entity_name is None:
            self.entity_name = self.subject_name
        elif self.subject_name is None:
            self.subject_name = self.entity_name
        if self.variant is None:
            self.variant = self.version
        elif self.version is None:
            self.version = self.variant
        if self.same_entity_as_previous is None:
            self.same_entity_as_previous = self.same_subject_as_previous
        elif self.same_subject_as_previous is None:
            self.same_subject_as_previous = self.same_entity_as_previous
        if self.camera_viewpoint is None:
            self.camera_viewpoint = self.viewpoint
        elif self.viewpoint is None:
            self.viewpoint = self.camera_viewpoint
        if self.interior_or_exterior is None:
            self.interior_or_exterior = self.interior_exterior
        elif self.interior_exterior is None:
            self.interior_exterior = self.interior_or_exterior
        if self.shot_type is None:
            self.shot_type = self.shot_scale
        elif self.shot_scale is None:
            self.shot_scale = self.shot_type
        if not self.segment_ids:
            self.segment_ids = list(self.evidence_segment_ids)
        if not self.evidence_segment_ids:
            self.evidence_segment_ids = list(self.segment_ids)
        if not self.frame_ids:
            self.frame_ids = list(self.evidence_frame_ids)
        if not self.evidence_frame_ids:
            self.evidence_frame_ids = list(self.frame_ids)
        if self.temporal_basis == "unknown":
            self.temporal_basis = (
                "interval" if self.time_basis == "observed_interval" else "unknown"
            )
        if self.evidence_kind is None and self.evidence:
            kinds = {item.source for item in self.evidence}
            self.evidence_kind = next(iter(kinds)) if len(kinds) == 1 else "mixed"
        if not self.unknown_conditions:
            self.unknown_conditions = list(self.unknown_fields)
        if not self.unknown_fields:
            self.unknown_fields = list(self.unknown_conditions)
        return self


class VideoSequenceWindow(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    video_id: UUID
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    event_ids: list[UUID] = Field(default_factory=list)
    ordered_summary: str = ""
    subject_ids: list[str] = Field(default_factory=list)
    action_continuity: bool | None = None
    scene_transitions: list[str] = Field(default_factory=list)
    source_cut_boundaries: list[int] = Field(default_factory=list)
    pollution_ranges: list[tuple[int, int, str]] = Field(default_factory=list)
    continuity_status: ContinuityStatus = "unknown_continuity"
    protocol_version: str = PROTOCOL_VERSION
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_range(self) -> "VideoSequenceWindow":
        if self.end_ms <= self.start_ms:
            raise ValueError("window end_ms must be greater than start_ms")
        if any(start < self.start_ms or end > self.end_ms or end <= start
               for start, end, _ in self.pollution_ranges):
            raise ValueError("pollution range must be inside the window")
        return self


class ScriptVisualRequirement(BaseModel):
    id: str = Field(min_length=1)
    sentence_id: str = Field(min_length=1)
    clause_id: str = Field(min_length=1)
    source_quote: str = Field(min_length=1)
    source_text_hash: str = Field(min_length=1)
    source_char_start: int = Field(ge=0)
    source_char_end: int = Field(gt=0)
    subject: str | None = None
    action: str | None = None
    scene: str | None = None
    environment: str | None = None
    objects: list[str] = Field(default_factory=list)
    configurations: list[str] = Field(default_factory=list)
    quantities: list[str] = Field(default_factory=list)
    relations: list[str] = Field(default_factory=list)
    state_changes: list[str] = Field(default_factory=list)
    temporal_relation: str | None = None
    same_subject_required: bool = False
    continuous_action_required: bool = False
    simultaneous_required: bool = False
    accepted_expressions: list[str] = Field(default_factory=list)
    proof_expressions: list[str] = Field(default_factory=list)
    related_expressions: list[str] = Field(default_factory=list)
    generic_expressions: list[str] = Field(default_factory=list)
    must_have: list[str] = Field(default_factory=list)
    preferred: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    anchor_phrase: str | None = None
    importance: Importance = "A"
    candidate_scope: Literal[
        "same_video_preferred", "same_entity_required", "continuous_window_preferred",
        "separate_shots_allowed"
    ] = "continuous_window_preferred"
    protocol_version: str = PROTOCOL_VERSION
    origin: Literal["api", "local_fallback"] = "local_fallback"

    @model_validator(mode="after")
    def validate_source_range(self) -> "ScriptVisualRequirement":
        if self.source_char_end <= self.source_char_start:
            raise ValueError("source_char_end must be greater than source_char_start")
        if self.anchor_phrase is not None and self.anchor_phrase not in self.source_quote:
            raise ValueError("anchor_phrase must be an exact substring of source_quote")
        return self

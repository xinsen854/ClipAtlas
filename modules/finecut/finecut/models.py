from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator


class Clip(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    source_id: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    timeline_start_ms: int = Field(ge=0)
    duration_ms: int = Field(gt=0)
    source_in_ms: int = Field(ge=0)
    source_out_ms: int = Field(gt=0)
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    volume: float = Field(default=1.0, ge=0.0)
    transform: dict[str, float] = Field(default_factory=dict)
    effects: list[dict[str, object]] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_source_window(self) -> "Clip":
        if self.source_out_ms <= self.source_in_ms:
            raise ValueError("source_out_ms must be greater than source_in_ms")
        if self.source_out_ms - self.source_in_ms != self.duration_ms:
            raise ValueError("source duration must match duration_ms")
        return self


class Track(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    kind: Literal["video", "audio", "text", "overlay"]
    clips: list[Clip] = Field(default_factory=list)


class TimelineDocument(BaseModel):
    version: int = Field(default=1, ge=1)
    project_id: UUID
    source_plan_id: UUID
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: float = Field(gt=0)
    duration_ms: int = Field(gt=0)
    tracks: list[Track] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_clip_bounds(self) -> "TimelineDocument":
        for track in self.tracks:
            for clip in track.clips:
                if clip.timeline_start_ms + clip.duration_ms > self.duration_ms:
                    raise ValueError("clip exceeds document duration")
        return self


CandidateDisplayLevel = Literal[
    "S", "A", "B", "Generic", "Fallback/Source", "Fallback/Reuse"
]


class CandidateItem(BaseModel):
    requirement_id: str
    sentence_id: str | None = None
    source_quote: str | None = None
    importance: str | None = None
    candidate_type: str
    candidate_id: UUID | None = None
    media_id: UUID
    source_in_ms: int = Field(ge=0)
    source_out_ms: int = Field(gt=0)
    anchor_in_ms: int | None = Field(default=None, ge=0)
    anchor_out_ms: int | None = Field(default=None, ge=0)
    continuity_status: str | None = None
    display_level: CandidateDisplayLevel
    pollution_level: str | None = None
    visual_family: str | None = None
    presentation_type: str | None = None
    subject_score: float = 0.0
    action_score: float = 0.0
    scene_score: float = 0.0
    environment_score: float = 0.0
    object_score: float = 0.0
    configuration_score: float = 0.0
    quantity_score: float = 0.0
    relation_score: float = 0.0
    order_score: float = 0.0
    vector_score: float = 0.0
    preliminary_level: str = "candidate"


class CandidateList(BaseModel):
    context_id: UUID
    items: list[CandidateItem] = Field(default_factory=list)


class NarrationSegmentReference(BaseModel):
    id: UUID
    text: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)


class NarrationReference(BaseModel):
    track_id: UUID
    revision: int = Field(ge=1)
    audio_uri: str | None = None
    duration_ms: int = Field(ge=0)
    segments: list[NarrationSegmentReference] = Field(default_factory=list)


class MediaReference(BaseModel):
    media_id: UUID
    source_uri: str

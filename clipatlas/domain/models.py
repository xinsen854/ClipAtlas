from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator
from clipatlas.domain.evidence import EvidenceStatement


def utc_now() -> datetime:
    return datetime.now(UTC)


class SegmentSource(StrEnum):
    SCENE_DETECTION = "scene_detection"
    AI = "ai"
    MANUAL = "manual"


class AnnotationOrigin(StrEnum):
    AI = "ai"
    HUMAN = "human"


class ObjectiveFactLayer(StrEnum):
    """The fixed fourteen factual layers stored for every visual segment."""

    SUBJECT = "subject"
    APPEARANCE = "appearance"
    ACTION = "action"
    OBJECT = "object"
    SCENE = "scene"
    TIME_WEATHER = "time_weather"
    SPATIAL_RELATION = "spatial_relation"
    EVENT = "event"
    EMOTION_EXPRESSION = "emotion_expression"
    SHOT_TYPE = "shot_type"
    COMPOSITION = "composition"
    CAMERA_MOTION = "camera_motion"
    LIGHTING_COLOR = "lighting_color"
    TEXT_AUDIO = "text_audio"


class ObjectiveFact(BaseModel):
    layer: ObjectiveFactLayer
    value: str = Field(min_length=1)
    evidence: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)
    statement: EvidenceStatement | None = None

    @model_validator(mode="after")
    def validate_statement_time(self) -> "ObjectiveFact":
        # Legacy annotations may contain unknown/point times. Typed evidence
        # explicitly declares its temporal basis instead of inventing duration.
        if self.statement is not None and self.statement.temporal_basis != "unknown":
            if self.start_ms is None or self.end_ms is None:
                raise ValueError("typed evidence requires absolute source times")
            if self.statement.temporal_basis == "point" and self.start_ms != self.end_ms:
                raise ValueError("point evidence must have equal timestamps")
            if self.statement.temporal_basis == "interval" and self.start_ms >= self.end_ms:
                raise ValueError("interval evidence must have positive duration")
        return self


class VideoAsset(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    filename: str
    source_uri: str
    duration_ms: int | None = Field(default=None, ge=0)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    fps: float | None = Field(default=None, gt=0)
    created_at: datetime = Field(default_factory=utc_now)
    fallback_role: Literal["normal", "generic", "never"] = "normal"


class VideoSegment(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    video_id: UUID
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    source: SegmentSource
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_time_range(self) -> "VideoSegment":
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        return self


class SemanticSpan(BaseModel):
    """A continuous, locally-derived editing window around evidence segments."""

    id: UUID = Field(default_factory=uuid4)
    video_id: UUID
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    safe_start_ms: int = Field(ge=0)
    safe_end_ms: int = Field(gt=0)
    summary: str = ""
    subjects: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    scenes: list[str] = Field(default_factory=list)
    objects: list[str] = Field(default_factory=list)
    facts: list[ObjectiveFact] = Field(default_factory=list)
    anchor_ranges: list[tuple[int, int]] = Field(default_factory=list)
    continuity_key: str
    visual_family: str | None = None
    presentation_type: str | None = None
    pollution_level: Literal["clean", "text_heavy", "blocked"] = "clean"
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_windows(self) -> "SemanticSpan":
        if self.end_ms <= self.start_ms:
            raise ValueError("semantic span end must be after start")
        if not (self.start_ms <= self.safe_start_ms < self.safe_end_ms <= self.end_ms):
            raise ValueError("safe range must be contained by semantic span")
        return self


class SemanticAnnotation(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    segment_id: UUID
    origin: AnnotationOrigin
    provider: str | None = None
    model: str | None = None
    description: str
    characters: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    scene: list[str] = Field(default_factory=list)
    emotions: list[str] = Field(default_factory=list)
    objects: list[str] = Field(default_factory=list)
    ocr: list[str] = Field(default_factory=list)
    shot_type: str | None = None
    camera_motion: str | None = None
    facts: list[ObjectiveFact] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    verified: bool = False
    locked: bool = False
    revision: int = Field(default=1, ge=1)
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)

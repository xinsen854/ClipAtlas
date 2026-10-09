from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator

from clipatlas.speech.alignment import NarrationAlignmentMap


def utc_now() -> datetime:
    return datetime.now(UTC)


class VoiceGender(StrEnum):
    MALE = "male"
    FEMALE = "female"
    NEUTRAL = "neutral"
    UNKNOWN = "unknown"
    UNRESTRICTED = "unrestricted"


class AgeStyle(StrEnum):
    YOUTH = "youth"
    YOUNG = "young"
    MATURE = "mature"
    ELDERLY = "elderly"
    UNKNOWN = "unknown"
    UNRESTRICTED = "unrestricted"


class RandomMode(StrEnum):
    NONE = "none"
    RANDOM_VOICE = "random_voice"
    RANDOM_PARAMETERS = "random_parameters"
    RANDOM_ALL = "random_all"


class NarrationSourceMode(StrEnum):
    TTS = "tts"
    IMPORTED = "imported"
    ESTIMATED = "estimated"


class TimingQuality(StrEnum):
    WORD_EXACT = "word_exact"
    UNIT_EXACT = "unit_exact"
    ALIGNED = "aligned"
    TRACK_ONLY = "track_only"
    ESTIMATED = "estimated"


class VoiceDescriptor(BaseModel):
    provider: str
    voice_id: str
    display_name: str
    gender: VoiceGender = VoiceGender.UNKNOWN
    age_style: AgeStyle = AgeStyle.UNKNOWN
    languages: list[str] = Field(default_factory=list)
    accents: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    preview_uri: str | None = None
    capability_overrides: dict[str, bool] = Field(default_factory=dict)


class SpeechProfile(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    provider: str
    model: str
    voice_id: str
    gender_constraint: VoiceGender | None = None
    age_style_constraint: AgeStyle | None = None
    language: str | None = None
    accent: str | None = None
    speed: float | None = Field(default=1.0, gt=0)
    pitch: float | None = None
    volume: float | None = None
    emotion: str | None = None
    style: str | None = None
    instruction: str | None = None
    random_seed: int | None = None
    random_mode: RandomMode = RandomMode.NONE
    locked: bool = False
    revision: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=utc_now)


class NarrationTrack(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    source_mode: NarrationSourceMode
    script_hash: str
    script: str | None = None
    alignment_source_id: UUID | None = None
    alignment_notes: list[str] = Field(default_factory=list)
    alignment_maps: list[NarrationAlignmentMap] = Field(default_factory=list)
    speech_profile_id: UUID | None = None
    provider: str | None = None
    model: str | None = None
    rule_pack_revision: int | None = Field(default=None, ge=1)
    audio_uri: str | None = None
    duration_ms: int = Field(ge=0)
    timing_quality: TimingQuality
    revision: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=utc_now)


class ProjectScript(BaseModel):
    project_id: UUID
    text: str = ""
    script_hash: str = ""
    updated_at: datetime | None = None


class NarrationUnit(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    track_id: UUID
    sequence: int = Field(ge=0)
    text: str
    text_hash: str
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)
    source: NarrationSourceMode = NarrationSourceMode.TTS
    audio_uri: str | None = None
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_time_range(self) -> "NarrationUnit":
        if (self.start_ms is None) != (self.end_ms is None):
            raise ValueError("start_ms and end_ms must either both be set or both be None")
        if self.start_ms is not None and self.end_ms is not None and self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        return self


class NarrationWordTiming(BaseModel):
    unit_id: UUID
    sequence: int = Field(ge=0)
    word: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_time_range(self) -> "NarrationWordTiming":
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        return self


class ProviderWordTiming(BaseModel):
    sequence: int = Field(ge=0)
    word: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_time_range(self) -> "ProviderWordTiming":
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        return self


class SpeechSynthesisRequest(BaseModel):
    text: str = Field(min_length=1)
    voice_id: str
    language: str | None = None
    speed: float | None = Field(default=1.0, gt=0)
    pitch: float | None = None
    volume: float | None = None
    emotion: str | None = None
    style: str | None = None
    instruction: str | None = None
    output_format: str = "wav"
    sample_rate: int | None = Field(default=None, gt=0)


class SpeechSynthesisResult(BaseModel):
    provider: str
    model: str
    audio_bytes: bytes
    output_format: str
    sample_rate: int | None = Field(default=None, gt=0)
    duration_ms: int | None = Field(default=None, ge=0)
    word_timings: list[ProviderWordTiming] = Field(default_factory=list)
    raw_payload: dict[str, Any] = Field(default_factory=dict)

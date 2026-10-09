from datetime import datetime
from enum import StrEnum
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from clipatlas.domain.models import utc_now


class ASRChunkStatus(StrEnum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ASRWord(BaseModel):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    text: str
    punctuation: str = ""

    @model_validator(mode="after")
    def validate_range(self) -> "ASRWord":
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        return self


class ASRSentence(BaseModel):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    text: str
    words: list[ASRWord] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_range(self) -> "ASRSentence":
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        return self


class ASRTextMatch(BaseModel):
    video_id: UUID
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    text: str
    revision: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_range(self) -> "ASRTextMatch":
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        return self


class ASRAudioChunk(BaseModel):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    path: Path

    @model_validator(mode="after")
    def validate_range(self) -> "ASRAudioChunk":
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        return self


class ASRChunkRecord(BaseModel):
    video_id: UUID
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    provider: str
    model: str
    revision: int = Field(ge=1)
    status: ASRChunkStatus
    attempt_count: int = Field(ge=0)
    last_error: str | None = None
    sentences: list[ASRSentence] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_range(self) -> "ASRChunkRecord":
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        return self

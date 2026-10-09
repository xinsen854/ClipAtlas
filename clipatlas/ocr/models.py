from datetime import datetime
from enum import StrEnum
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from clipatlas.domain.models import utc_now


class OCRSampleStatus(StrEnum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class OCRFrame(BaseModel):
    timestamp_ms: int = Field(ge=0)
    path: Path


class OCRSampleRecord(BaseModel):
    video_id: UUID
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    interval_ms: int = Field(gt=0)
    provider: str
    model: str
    revision: int = Field(ge=1)
    status: OCRSampleStatus
    attempt_count: int = Field(ge=0)
    last_error: str | None = None
    text: str = ""
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_range(self) -> "OCRSampleRecord":
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        if self.end_ms - self.start_ms > self.interval_ms:
            raise ValueError("OCR sample range must not exceed interval_ms")
        return self


class OCRSpan(BaseModel):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    text: str

    @model_validator(mode="after")
    def validate_range(self) -> "OCRSpan":
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        return self


class OCRTextMatch(BaseModel):
    video_id: UUID
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    text: str
    revision: int = Field(ge=1)
    interval_ms: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_range(self) -> "OCRTextMatch":
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        return self

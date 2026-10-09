from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator

from clipatlas.domain.models import utc_now


class SegmentEmbedding(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    segment_id: UUID
    annotation_id: UUID
    annotation_revision: int = Field(ge=1)
    provider: str
    model: str
    dimensions: int = Field(gt=0)
    vector: list[float] = Field(min_length=1)
    effective: bool = True
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_dimensions(self) -> "SegmentEmbedding":
        if len(self.vector) != self.dimensions:
            raise ValueError("vector length must match dimensions")
        return self


class VideoChunkEmbedding(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    video_id: UUID
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    provider: str
    model: str
    dimensions: int = Field(gt=0)
    chunk_duration_ms: int = Field(gt=0)
    overlap_ms: int = Field(ge=0)
    vector: list[float] = Field(min_length=1)
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_record(self) -> "VideoChunkEmbedding":
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        if self.overlap_ms >= self.chunk_duration_ms:
            raise ValueError("overlap_ms must be smaller than chunk_duration_ms")
        if len(self.vector) != self.dimensions:
            raise ValueError("vector length must match dimensions")
        return self


class QueryEmbedding(BaseModel):
    """A query vector prepared during script confirmation, never during editing."""

    requirement_id: str
    source_text_hash: str
    provider: str
    model: str
    dimensions: int = Field(gt=0)
    protocol_version: str
    event_index_revision: str
    vector: list[float] = Field(min_length=1)
    api_request_count: int = Field(default=1, ge=0)
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_dimensions(self) -> "QueryEmbedding":
        if len(self.vector) != self.dimensions:
            raise ValueError("query vector length must match dimensions")
        return self

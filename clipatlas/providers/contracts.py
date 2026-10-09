from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from clipatlas.domain.models import SemanticAnnotation


class ProviderCapabilities(BaseModel):
    native_video_input: bool = False
    image_input: bool = False
    audio_understanding: bool = False
    ocr: bool = False
    temporal_search: bool = False
    semantic_segmentation: bool = False
    embeddings: bool = False
    structured_output: bool = False


class ProviderDescriptor(BaseModel):
    name: str
    capabilities: ProviderCapabilities


class AnalyzeSegmentRequest(BaseModel):
    video_id: UUID
    segment_id: UUID
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    source_uri: str
    frame_uris: list[str] = Field(default_factory=list)
    frame_timestamps_ms: list[int] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_frame_times(self) -> "AnalyzeSegmentRequest":
        if self.frame_timestamps_ms:
            if len(self.frame_timestamps_ms) != len(self.frame_uris):
                raise ValueError("frame timestamps must correspond one-to-one to frame URIs")
            if any(t < self.start_ms or t >= self.end_ms for t in self.frame_timestamps_ms):
                raise ValueError("frame timestamps must be within the source segment")
            if self.frame_timestamps_ms != sorted(set(self.frame_timestamps_ms)):
                raise ValueError("frame timestamps must be strictly increasing")
        return self


class AnalyzeSegmentResult(BaseModel):
    provider: str
    model: str | None = None
    annotation: SemanticAnnotation
    query_relevance_score: float | None = Field(default=None, ge=0.0, le=1.0)
    query_relevance_reason: str | None = None


@runtime_checkable
class VideoUnderstandingProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def capabilities(self) -> ProviderCapabilities: ...

    async def analyze_segment(self, request: AnalyzeSegmentRequest) -> AnalyzeSegmentResult: ...


class TemporalSearchHit(BaseModel):
    video_id: UUID
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    score: float | None = None
    provider_payload: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class TemporalSearchProvider(VideoUnderstandingProvider, Protocol):
    async def temporal_search(
        self, query: str, video_ids: list[UUID] | None = None
    ) -> list[TemporalSearchHit]: ...

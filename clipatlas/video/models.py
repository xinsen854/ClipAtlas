from uuid import UUID

from pydantic import BaseModel, Field

from clipatlas.domain.models import VideoAsset, VideoSegment


class MediaMetadata(BaseModel):
    duration_ms: int = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: float = Field(gt=0)
    video_codec: str
    has_audio: bool


class IngestedVideo(BaseModel):
    video: VideoAsset
    metadata: MediaMetadata
    segments: list[VideoSegment]
    frames_by_segment: dict[UUID, list[str]]

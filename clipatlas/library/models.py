from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from clipatlas.domain.models import utc_now


class LibraryItemStatus(StrEnum):
    QUEUED = "QUEUED"
    PROBING = "PROBING"
    SCENE_DETECTION = "SCENE_DETECTION"
    FRAME_EXTRACTION = "FRAME_EXTRACTION"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    MISSING = "MISSING"


class LibraryRoot(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    path: str
    recursive: bool = True
    enabled: bool = True
    # 素材根归属的项目；None 表示升级前遗留的全局素材（在所有项目可见）。
    project_id: UUID | None = None
    created_at: datetime = Field(default_factory=utc_now)


class LibraryItem(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    root_id: UUID
    source_path: str
    size_bytes: int = Field(ge=0)
    mtime_ns: int = Field(ge=0)
    fingerprint: str
    processed_fingerprint: str | None = None
    status: LibraryItemStatus = LibraryItemStatus.QUEUED
    video_id: UUID | None = None
    attempts: int = Field(default=0, ge=0)
    last_error: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ScanReport(BaseModel):
    discovered: int = 0
    changed: int = 0
    missing: int = 0
    unchanged: int = 0

    def add(self, other: "ScanReport") -> "ScanReport":
        return ScanReport(
            discovered=self.discovered + other.discovered,
            changed=self.changed + other.changed,
            missing=self.missing + other.missing,
            unchanged=self.unchanged + other.unchanged,
        )

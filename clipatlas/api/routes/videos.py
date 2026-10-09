from collections.abc import AsyncIterator
from typing import Annotated, Literal, Protocol, cast
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel

from clipatlas.catalog.segment_roles import SegmentFallbackRoleStore
from clipatlas.catalog.store import CatalogStore, VideoAnnotationStats
from clipatlas.domain.models import SemanticAnnotation, VideoAsset, VideoSegment
from clipatlas.library.index_progress import VideoIndexProgress
from clipatlas.video.ingest import VideoIngestService
from clipatlas.video.models import IngestedVideo

router = APIRouter(prefix="/api/v1/videos", tags=["videos"])
_CHUNK_SIZE = 1024 * 1024


class VideoDetailResponse(BaseModel):
    video: VideoAsset
    segment_count: int
    annotation_stats: VideoAnnotationStats


class SegmentSummary(BaseModel):
    segment: VideoSegment
    annotation: SemanticAnnotation | None
    fallback_role: Literal["normal", "generic", "review_placeholder", "never"] = "normal"


class SegmentPage(BaseModel):
    items: list[SegmentSummary]
    total: int
    limit: int
    offset: int


class VideoFallbackRoleRequest(BaseModel):
    role: Literal["normal", "generic", "never"]


class IndexProgressReaderLike(Protocol):
    def get(self, video_id: UUID) -> VideoIndexProgress: ...


def _service(request: Request) -> VideoIngestService:
    service = request.app.state.video_ingest_service
    if not hasattr(service, "ingest"):
        raise TypeError("video ingest service is not configured")
    return cast(VideoIngestService, service)


def _catalog(request: Request) -> CatalogStore:
    catalog = getattr(request.app.state, "library_catalog", None)
    if not isinstance(catalog, CatalogStore):
        raise TypeError("library catalog is not configured")
    return catalog


def _index_progress(request: Request) -> IndexProgressReaderLike:
    reader = getattr(request.app.state, "library_index_progress", None)
    if reader is None or not hasattr(reader, "get"):
        raise TypeError("library index progress reader is not configured")
    return cast(IndexProgressReaderLike, reader)


def _video_or_404(catalog: CatalogStore, video_id: UUID) -> VideoAsset:
    video = catalog.get_video(video_id)
    if video is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="video not found",
        )
    return video


async def _upload_chunks(file: UploadFile) -> AsyncIterator[bytes]:
    while True:
        chunk = await file.read(_CHUNK_SIZE)
        if not chunk:
            break
        yield chunk


@router.post("", response_model=IngestedVideo, status_code=status.HTTP_201_CREATED)
async def upload_video(
    request: Request,
    file: Annotated[UploadFile, File()],
) -> IngestedVideo:
    source_name = file.filename or "upload.bin"
    return await _service(request).ingest(
        source_name=source_name,
        chunks=_upload_chunks(file),
    )


@router.get("/{video_id}/segments", response_model=SegmentPage)
def list_video_segments(
    request: Request,
    video_id: UUID,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SegmentPage:
    catalog = _catalog(request)
    _video_or_404(catalog, video_id)
    segments = catalog.list_segments(video_id, limit=limit, offset=offset)
    roles = SegmentFallbackRoleStore(catalog)
    return SegmentPage(
        items=[
            SegmentSummary(
                segment=segment,
                annotation=catalog.get_effective_annotation(segment.id),
                fallback_role=roles.get_role(segment.id),
            )
            for segment in segments
        ],
        total=catalog.count_segments(video_id),
        limit=limit,
        offset=offset,
    )


@router.get("/{video_id}/index-progress", response_model=VideoIndexProgress)
def get_video_index_progress(request: Request, video_id: UUID) -> VideoIndexProgress:
    catalog = _catalog(request)
    _video_or_404(catalog, video_id)
    return _index_progress(request).get(video_id)


@router.get("/{video_id}", response_model=VideoDetailResponse)
def get_video(request: Request, video_id: UUID) -> VideoDetailResponse:
    catalog = _catalog(request)
    video = _video_or_404(catalog, video_id)
    stats = catalog.get_video_annotation_stats(video_id)
    return VideoDetailResponse(
        video=video,
        segment_count=stats.segments_total,
        annotation_stats=stats,
    )


@router.patch("/{video_id}/fallback-role", response_model=VideoAsset)
def update_video_fallback_role(
    request: Request, video_id: UUID, body: VideoFallbackRoleRequest,
) -> VideoAsset:
    catalog = _catalog(request)
    _video_or_404(catalog, video_id)
    catalog.set_video_fallback_role(video_id, body.role)
    return _video_or_404(catalog, video_id)

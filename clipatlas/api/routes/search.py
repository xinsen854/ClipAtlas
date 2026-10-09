from typing import Annotated, Literal, Protocol, cast
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status

from clipatlas.retrieval.hybrid import HybridSearchHit
from clipatlas.retrieval.search import CoarseVideoSearchHit, SemanticSearchHit
from clipatlas.retrieval.video_profiles import VideoIndexProfile, get_video_index_profile

router = APIRouter(prefix="/api/v1/search", tags=["search"])


class SemanticSearchServiceLike(Protocol):
    async def search(
        self,
        query: str,
        limit: int = 10,
        video_ids: list[UUID] | None = None,
    ) -> list[SemanticSearchHit]: ...


class VideoChunkSearchServiceLike(Protocol):
    async def search(
        self,
        query: str,
        limit: int = 10,
        video_ids: list[UUID] | None = None,
        profile: VideoIndexProfile = ...,
    ) -> list[CoarseVideoSearchHit]: ...


class HybridSearchServiceLike(Protocol):
    async def search(
        self,
        query: str,
        limit: int = 10,
        video_ids: list[UUID] | None = None,
    ) -> list[HybridSearchHit]: ...


def _service(request: Request) -> SemanticSearchServiceLike:
    service = getattr(request.app.state, "semantic_search_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="semantic search is not configured",
        )
    if not hasattr(service, "search"):
        raise TypeError("semantic search service is not configured")
    return cast(SemanticSearchServiceLike, service)


def _video_chunk_service(request: Request) -> VideoChunkSearchServiceLike:
    service = getattr(request.app.state, "video_chunk_search_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="video chunk search is not configured",
        )
    if not hasattr(service, "search"):
        raise TypeError("video chunk search service is not configured")
    return cast(VideoChunkSearchServiceLike, service)


def _hybrid_service(request: Request) -> HybridSearchServiceLike:
    service = getattr(request.app.state, "hybrid_search_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="hybrid search is not configured",
        )
    if not hasattr(service, "search"):
        raise TypeError("hybrid search service is not configured")
    return cast(HybridSearchServiceLike, service)


def _scoped_video_ids(
    request: Request,
    project_id: UUID | None,
    video_ids: list[UUID] | None,
) -> list[UUID] | None:
    if project_id is None:
        return video_ids
    catalog = getattr(request.app.state, "library_catalog", None)
    lookup = getattr(catalog, "list_video_ids_for_project", None)
    if not callable(lookup):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="project library scope is not configured",
        )
    allowed = list(lookup(project_id))
    if video_ids is None:
        return allowed
    allowed_set = set(allowed)
    return list(dict.fromkeys(video_id for video_id in video_ids if video_id in allowed_set))


@router.get("/segments", response_model=list[SemanticSearchHit])
async def search_segments(
    request: Request,
    q: Annotated[str, Query(min_length=1)],
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
    video_ids: Annotated[list[UUID] | None, Query()] = None,
    project_id: UUID | None = None,
) -> list[SemanticSearchHit]:
    query = q.strip()
    if not query:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="query must not be blank",
        )
    return await _service(request).search(
        query,
        limit=limit,
        video_ids=_scoped_video_ids(request, project_id, video_ids),
    )


@router.get("/video-chunks", response_model=list[CoarseVideoSearchHit])
async def search_video_chunks(
    request: Request,
    q: Annotated[str, Query(min_length=1)],
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
    video_ids: Annotated[list[UUID] | None, Query()] = None,
    project_id: UUID | None = None,
    granularity: Annotated[Literal["5s", "30s"], Query()] = "5s",
) -> list[CoarseVideoSearchHit]:
    query = q.strip()
    if not query:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="query must not be blank",
        )
    profile = get_video_index_profile(granularity)
    return await _video_chunk_service(request).search(
        query,
        limit=limit,
        video_ids=_scoped_video_ids(request, project_id, video_ids),
        profile=profile,
    )


@router.get("/hybrid", response_model=list[HybridSearchHit])
async def search_hybrid(
    request: Request,
    q: Annotated[str, Query(min_length=1)],
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
    video_ids: Annotated[list[UUID] | None, Query()] = None,
    project_id: UUID | None = None,
) -> list[HybridSearchHit]:
    query = q.strip()
    if not query:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="query must not be blank",
        )
    return await _hybrid_service(request).search(
        query,
        limit=limit,
        video_ids=_scoped_video_ids(request, project_id, video_ids),
    )

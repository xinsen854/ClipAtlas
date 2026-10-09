from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from clipatlas.catalog.segment_roles import SegmentFallbackRoleStore
from clipatlas.catalog.store import CatalogStore

router = APIRouter(prefix="/api/v1/library", tags=["library"])

SegmentFallbackRoleValue = Literal[
    "normal", "generic", "review_placeholder", "never"
]


class SegmentFallbackRoleRequest(BaseModel):
    role: SegmentFallbackRoleValue


class SegmentFallbackRoleResponse(BaseModel):
    segment_id: UUID
    role: SegmentFallbackRoleValue


def _roles(request: Request) -> SegmentFallbackRoleStore:
    catalog = getattr(request.app.state, "library_catalog", None)
    if not isinstance(catalog, CatalogStore):
        raise TypeError("library catalog is not configured")
    return SegmentFallbackRoleStore(catalog)


@router.get(
    "/segments/{segment_id}/fallback-role",
    response_model=SegmentFallbackRoleResponse,
)
def get_segment_fallback_role(
    request: Request,
    segment_id: UUID,
) -> SegmentFallbackRoleResponse:
    roles = _roles(request)
    catalog = roles._catalog
    if catalog.get_segment(segment_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="library segment not found",
        )
    return SegmentFallbackRoleResponse(
        segment_id=segment_id,
        role=roles.get_role(segment_id),
    )


@router.patch(
    "/segments/{segment_id}/fallback-role",
    response_model=SegmentFallbackRoleResponse,
)
def set_segment_fallback_role(
    request: Request,
    segment_id: UUID,
    body: SegmentFallbackRoleRequest,
) -> SegmentFallbackRoleResponse:
    roles = _roles(request)
    try:
        roles.set_role(segment_id, body.role)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="library segment not found",
        ) from exc
    return SegmentFallbackRoleResponse(
        segment_id=segment_id,
        role=roles.get_role(segment_id),
    )

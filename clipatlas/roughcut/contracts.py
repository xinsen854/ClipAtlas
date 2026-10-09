from collections.abc import Sequence
from typing import Protocol, runtime_checkable
from uuid import UUID

from clipatlas.domain.models import SemanticAnnotation


class RoughCutSearchHit(Protocol):
    segment_id: UUID
    video_id: UUID
    source_uri: str
    source_start_ms: int
    source_end_ms: int
    score: float
    annotation: SemanticAnnotation


@runtime_checkable
class SegmentSearch(Protocol):
    async def search(
        self,
        query: str,
        limit: int = 10,
        video_ids: list[UUID] | None = None,
    ) -> Sequence[RoughCutSearchHit]: ...

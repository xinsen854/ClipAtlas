import math
from uuid import UUID

from pydantic import BaseModel

from clipatlas.catalog.store import CatalogStore
from clipatlas.domain.models import SemanticAnnotation, VideoAsset
from clipatlas.embeddings.contracts import EmbeddingProvider, VideoEmbeddingProvider
from clipatlas.retrieval.video_profiles import (
    DEFAULT_VIDEO_INDEX_PROFILE,
    VideoIndexProfile,
)


class SemanticSearchHit(BaseModel):
    segment_id: UUID
    video_id: UUID
    source_uri: str
    source_start_ms: int
    source_end_ms: int
    score: float
    effective_description: str
    annotation: SemanticAnnotation
    embedding_provider: str
    embedding_model: str
    embedding_dimensions: int


class CoarseVideoSearchHit(BaseModel):
    video_id: UUID
    filename: str
    source_uri: str
    source_start_ms: int
    source_end_ms: int
    score: float
    embedding_provider: str
    embedding_model: str
    embedding_dimensions: int
    chunk_duration_ms: int
    overlap_ms: int


def cosine_similarity(left: list[float], right: list[float]) -> float | None:
    if not left or len(left) != len(right):
        return None
    if any(not math.isfinite(value) for value in left):
        return None
    if any(not math.isfinite(value) for value in right):
        return None

    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return None

    score = sum(a * b for a, b in zip(left, right, strict=True)) / (
        left_norm * right_norm
    )
    return score if math.isfinite(score) else None


class SemanticSearchService:
    def __init__(self, *, store: CatalogStore, provider: EmbeddingProvider) -> None:
        self._store = store
        self._provider = provider

    async def search(
        self,
        query: str,
        limit: int = 10,
        video_ids: list[UUID] | None = None,
        *,
        query_vector: list[float] | None = None,
    ) -> list[SemanticSearchHit]:
        if limit <= 0:
            return []

        if query_vector is None:
            query_vector = (await self._provider.embed_query(query)).values
        allowed_video_ids = set(video_ids) if video_ids is not None else None
        hits: list[SemanticSearchHit] = []

        embeddings = self._store.list_effective_embeddings(
            provider=self._provider.name,
            model=self._provider.model,
            dimensions=self._provider.dimensions,
        )
        for embedding in embeddings:
            annotation = self._store.get_effective_annotation(embedding.segment_id)
            if annotation is None:
                continue
            if (
                embedding.annotation_id != annotation.id
                or embedding.annotation_revision != annotation.revision
            ):
                continue

            segment = self._store.get_segment(embedding.segment_id)
            if segment is None:
                continue
            if allowed_video_ids is not None and segment.video_id not in allowed_video_ids:
                continue

            video = self._store.get_video(segment.video_id)
            if video is None:
                continue

            score = cosine_similarity(query_vector, embedding.vector)
            if score is None:
                continue

            hits.append(
                SemanticSearchHit(
                    segment_id=segment.id,
                    video_id=video.id,
                    source_uri=video.source_uri,
                    source_start_ms=segment.start_ms,
                    source_end_ms=segment.end_ms,
                    score=score,
                    effective_description=annotation.description,
                    annotation=annotation,
                    embedding_provider=embedding.provider,
                    embedding_model=embedding.model,
                    embedding_dimensions=embedding.dimensions,
                )
            )

        hits.sort(key=lambda hit: (-hit.score, str(hit.segment_id)))
        return hits[:limit]

    async def search_cached(
        self,
        requirement_id: str,
        *,
        source_text_hash: str,
        protocol_version: str,
        event_index_revision: str,
        limit: int = 20,
        video_ids: list[UUID] | None = None,
    ) -> list[SemanticSearchHit]:
        """Search using a query vector prepared before editing began."""
        cached = self._store.get_query_embedding(
            requirement_id,
            source_text_hash=source_text_hash,
            provider=self._provider.name,
            model=self._provider.model,
            dimensions=self._provider.dimensions,
            protocol_version=protocol_version,
            event_index_revision=event_index_revision,
        )
        if cached is None:
            return []
        return await self.search(
            "", limit=limit, video_ids=video_ids, query_vector=cached.vector,
        )


class CoarseVideoSearchService:
    def __init__(self, *, store: CatalogStore, provider: VideoEmbeddingProvider) -> None:
        self._store = store
        self._provider = provider

    async def search(
        self,
        query: str,
        limit: int = 10,
        video_ids: list[UUID] | None = None,
        profile: VideoIndexProfile = DEFAULT_VIDEO_INDEX_PROFILE,
        *,
        query_vector: list[float] | None = None,
    ) -> list[CoarseVideoSearchHit]:
        if limit <= 0:
            return []

        if query_vector is None:
            query_vector = (await self._provider.embed_query(query)).values
        embeddings = self._store.list_video_chunk_embeddings_for_search(
            provider=self._provider.name,
            model=self._provider.model,
            dimensions=self._provider.effective_dimensions,
            chunk_duration_ms=profile.chunk_duration_ms,
            overlap_ms=profile.overlap_ms,
            video_ids=video_ids,
        )
        hits: list[CoarseVideoSearchHit] = []
        videos: dict[UUID, VideoAsset | None] = {}
        for embedding in embeddings:
            if embedding.video_id not in videos:
                videos[embedding.video_id] = self._store.get_video(embedding.video_id)
            video = videos[embedding.video_id]
            if video is None:
                continue

            score = cosine_similarity(query_vector, embedding.vector)
            if score is None:
                continue

            hits.append(
                CoarseVideoSearchHit(
                    video_id=video.id,
                    filename=video.filename,
                    source_uri=video.source_uri,
                    source_start_ms=embedding.start_ms,
                    source_end_ms=embedding.end_ms,
                    score=score,
                    embedding_provider=embedding.provider,
                    embedding_model=embedding.model,
                    embedding_dimensions=embedding.dimensions,
                    chunk_duration_ms=embedding.chunk_duration_ms,
                    overlap_ms=embedding.overlap_ms,
                )
            )

        hits.sort(
            key=lambda hit: (
                -hit.score,
                str(hit.video_id),
                hit.source_start_ms,
                hit.source_end_ms,
            )
        )
        return hits[:limit]

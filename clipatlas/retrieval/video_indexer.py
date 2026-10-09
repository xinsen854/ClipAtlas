import asyncio
import logging
import time
from pathlib import Path

from clipatlas.catalog.checkpoints import VideoChunkCheckpointStore
from clipatlas.catalog.store import CatalogStore
from clipatlas.concurrency import bounded_map
from clipatlas.domain.models import VideoAsset
from clipatlas.embeddings.contracts import VideoEmbeddingProvider
from clipatlas.retrieval.models import VideoChunkEmbedding
from clipatlas.retrieval.video_profiles import (
    DEFAULT_VIDEO_INDEX_PROFILE,
    VideoIndexProfile,
)
from clipatlas.video.chunks import (
    VideoChunkMaterializer,
    VideoChunkSpan,
    VideoChunkTooSmallError,
    plan_video_chunks,
)


class CoarseVideoIndexer:
    """Build a resumable video-vector index without detailed semantic analysis."""

    def __init__(
        self,
        *,
        catalog_store: CatalogStore,
        checkpoint_store: VideoChunkCheckpointStore,
        provider: VideoEmbeddingProvider,
        materializer: VideoChunkMaterializer,
        chunk_root: Path,
        profile: VideoIndexProfile = DEFAULT_VIDEO_INDEX_PROFILE,
        concurrency: int = 1,
    ) -> None:
        self._catalog_store = catalog_store
        self._checkpoint_store = checkpoint_store
        self._provider = provider
        self._materializer = materializer
        self._chunk_root = chunk_root
        self._profile = profile
        if concurrency < 1:
            raise ValueError("concurrency must be positive")
        self._concurrency = concurrency
        self._api_slots = asyncio.Semaphore(concurrency)

    async def index_video(
        self,
        video: VideoAsset,
        source: Path,
        *,
        force: bool = False,
    ) -> list[VideoChunkEmbedding]:
        if video.duration_ms is None:
            raise ValueError("video duration is required for video indexing")

        spans = plan_video_chunks(
            video.duration_ms,
            chunk_duration_ms=self._profile.chunk_duration_ms,
            overlap_ms=self._profile.overlap_ms,
        )
        async def index_span(span: VideoChunkSpan) -> VideoChunkEmbedding:
            existing = self._catalog_store.get_video_chunk_embedding(
                video.id,
                start_ms=span.start_ms,
                end_ms=span.end_ms,
                provider=self._provider.name,
                model=self._provider.model,
                dimensions=self._provider.effective_dimensions,
                chunk_duration_ms=self._profile.chunk_duration_ms,
                overlap_ms=self._profile.overlap_ms,
            )
            if (
                not force
                and existing is not None
                and self._checkpoint_store.is_completed(
                    video.id,
                    span.start_ms,
                    span.end_ms,
                    self._provider.name,
                    self._provider.model,
                    chunk_duration_ms=self._profile.chunk_duration_ms,
                    overlap_ms=self._profile.overlap_ms,
                )
            ):
                return existing

            self._checkpoint_store.mark_processing(
                video.id,
                span.start_ms,
                span.end_ms,
                self._provider.name,
                self._provider.model,
                chunk_duration_ms=self._profile.chunk_duration_ms,
                overlap_ms=self._profile.overlap_ms,
            )
            try:
                chunk_path = await self._materializer.materialize(
                    source,
                    video_id=video.id,
                    span=span,
                    chunk_root=self._chunk_root,
                )
                async with self._api_slots:
                    started = time.monotonic()
                    embedding = await self._provider.embed_video(chunk_path)
                    logging.getLogger(__name__).info(
                        "visual video=%s start_ms=%s cloud_seconds=%.3f",
                        video.id, span.start_ms, time.monotonic() - started,
                    )
                record = VideoChunkEmbedding(
                    video_id=video.id,
                    start_ms=span.start_ms,
                    end_ms=span.end_ms,
                    provider=self._provider.name,
                    model=self._provider.model,
                    dimensions=self._provider.effective_dimensions,
                    chunk_duration_ms=self._profile.chunk_duration_ms,
                    overlap_ms=self._profile.overlap_ms,
                    vector=embedding.values,
                )
                self._catalog_store.save_video_chunk_embedding(record)
                self._checkpoint_store.mark_completed(
                    video.id,
                    span.start_ms,
                    span.end_ms,
                    self._provider.name,
                    self._provider.model,
                    chunk_duration_ms=self._profile.chunk_duration_ms,
                    overlap_ms=self._profile.overlap_ms,
                )
            except VideoChunkTooSmallError as exc:
                # 分片即使 raw copy 也小于上游上传下限（短视频 / 极简画面）：
                # 无法上传，跳过该 span 而不是让整个视频解析失败。
                logging.getLogger(__name__).warning(
                    "visual video=%s span=%s..%s skipped (too small): %s",
                    video.id, span.start_ms, span.end_ms, exc,
                )
                self._checkpoint_store.mark_completed(
                    video.id,
                    span.start_ms,
                    span.end_ms,
                    self._provider.name,
                    self._provider.model,
                    chunk_duration_ms=self._profile.chunk_duration_ms,
                    overlap_ms=self._profile.overlap_ms,
                )
                return None
            except Exception as exc:
                message = str(exc).strip() or type(exc).__name__
                self._checkpoint_store.mark_failed(
                    video.id,
                    span.start_ms,
                    span.end_ms,
                    self._provider.name,
                    self._provider.model,
                    chunk_duration_ms=self._profile.chunk_duration_ms,
                    overlap_ms=self._profile.overlap_ms,
                    error=message[:2000],
                )
                raise
            return record

        results = await bounded_map(
            spans, index_span, concurrency=self._concurrency + (self._concurrency > 1),
            label=f"visual video={video.id}",
        )
        return [record for record in results if record is not None]

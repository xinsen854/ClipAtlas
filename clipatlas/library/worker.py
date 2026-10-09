import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Protocol
from uuid import UUID

from clipatlas.domain.models import AnnotationOrigin, SemanticAnnotation, VideoAsset
from clipatlas.library.models import LibraryItem, LibraryItemStatus
from clipatlas.library.store import LibraryStore
from clipatlas.providers.contracts import (
    AnalyzeSegmentRequest,
    VideoUnderstandingProvider,
)
from clipatlas.video.models import IngestedVideo


class LibraryProcessorLike(Protocol):
    async def prepare(
        self,
        item_id: UUID,
        source_path: Path,
        on_stage: Callable[[LibraryItemStatus], None],
    ) -> IngestedVideo: ...


class SemanticCatalogLike(Protocol):
    def save_prepared_video(self, prepared: IngestedVideo) -> None: ...

    def get_ingested_video(self, video_id: UUID) -> IngestedVideo | None: ...

    def save_annotation(self, annotation: SemanticAnnotation) -> None: ...

    def list_annotations(
        self,
        segment_id: UUID,
        origin: AnnotationOrigin | None = None,
    ) -> list[SemanticAnnotation]: ...

    def has_ai_annotation(self, segment_id: UUID, provider: str | None = None) -> bool: ...

    def rebuild_timeline_protocol(self, video_id: UUID) -> tuple[int, int]: ...


class SemanticIndexerLike(Protocol):
    async def index_segment(self, segment_id: UUID) -> bool: ...


class MediaTypeAnnotatorLike(Protocol):
    async def annotate_video(
        self, video_id: UUID, *, force: bool = False,
    ) -> dict[str, int]: ...


class VideoIndexerLike(Protocol):
    async def index_video(
        self, video: VideoAsset, source: Path, *, force: bool = False,
    ) -> object: ...


class TimedVideoIndexerLike(Protocol):
    async def index_video(
        self,
        video: VideoAsset,
        source: Path,
        *,
        force: bool = False,
    ) -> object: ...


class PreparedCheckpointLike(Protocol):
    def save(self, library_item_id: UUID, fingerprint: str, video_id: UUID) -> None: ...

    def get_video_id(self, library_item_id: UUID, fingerprint: str) -> UUID | None: ...


class SequentialLibraryWorker:
    def __init__(
        self,
        store: LibraryStore,
        processor: LibraryProcessorLike,
        catalog: SemanticCatalogLike | None = None,
        provider: VideoUnderstandingProvider | None = None,
        checkpoints: PreparedCheckpointLike | None = None,
        indexer: SemanticIndexerLike | None = None,
        video_indexer: VideoIndexerLike | None = None,
        asr_indexer: TimedVideoIndexerLike | None = None,
        ocr_indexer: TimedVideoIndexerLike | None = None,
        media_type_annotator: MediaTypeAnnotatorLike | None = None,
    ) -> None:
        self._store = store
        self._processor = processor
        self._catalog = catalog
        self._provider = provider
        self._checkpoints = checkpoints
        self._indexer = indexer
        self._video_indexer = video_indexer
        self._asr_indexer = asr_indexer
        self._ocr_indexer = ocr_indexer
        self._media_type_annotator = media_type_annotator
        self.operation_lock = asyncio.Lock()

    @property
    def indexer(self) -> SemanticIndexerLike | None:
        return self._indexer

    @property
    def video_indexer(self) -> VideoIndexerLike | None:
        return self._video_indexer

    async def _load_or_prepare(
        self,
        item: LibraryItem,
        on_stage: Callable[[LibraryItemStatus], None],
    ) -> IngestedVideo:
        if self._catalog is not None and self._checkpoints is not None:
            video_id = self._checkpoints.get_video_id(item.id, item.fingerprint)
            if video_id is not None:
                prepared = self._catalog.get_ingested_video(video_id)
                if prepared is not None:
                    return prepared

        prepared = await self._processor.prepare(
            item_id=item.id,
            source_path=Path(item.source_path),
            on_stage=on_stage,
        )
        if self._catalog is not None:
            root = self._store.get_root(item.root_id)
            item_project = root.project_id if root is not None else None
            self._catalog.save_prepared_video(prepared, project_id=item_project)
        if self._checkpoints is not None:
            self._checkpoints.save(item.id, item.fingerprint, prepared.video.id)
        return prepared

    async def _analyze_and_index_segments(
        self,
        prepared: IngestedVideo,
        *,
        force_reanalyze: bool = False,
    ) -> None:
        if self._catalog is None:
            return

        # 批注/索引进度：API 调用是大头，段之间并行可显著提速（默认 4 路并发）。
        concurrency = int(os.getenv("CLIPATLAS_ANNOTATION_CONCURRENCY", "8"))
        sem = asyncio.Semaphore(max(1, concurrency))

        async def process_segment(segment) -> None:
            async with sem:
                should_analyze = self._provider is not None and (
                    force_reanalyze
                    or not self._catalog.has_ai_annotation(
                        segment.id,
                        provider=self._provider.name,
                    )
                )
                if should_analyze and self._provider is not None:
                    from clipatlas.providers.evidence_contract import saved_frame_times
                    frame_uris = prepared.frames_by_segment.get(segment.id, [])
                    result = await self._provider.analyze_segment(
                        AnalyzeSegmentRequest(
                            video_id=prepared.video.id,
                            segment_id=segment.id,
                            start_ms=segment.start_ms,
                            end_ms=segment.end_ms,
                            source_uri=prepared.video.source_uri,
                            frame_uris=frame_uris,
                            frame_timestamps_ms=saved_frame_times(
                                frame_uris, segment.id, segment.start_ms, segment.end_ms,
                            ),
                            context={"analysis_scope": "segment"},
                        )
                    )
                    if result.annotation.segment_id != segment.id:
                        raise ValueError("provider returned annotation for a different segment")
                    annotation = result.annotation
                    if force_reanalyze:
                        ai_history = self._catalog.list_annotations(
                            segment.id,
                            origin=AnnotationOrigin.AI,
                        )
                        next_revision = max(
                            (existing.revision for existing in ai_history),
                            default=0,
                        ) + 1
                        annotation = annotation.model_copy(update={"revision": next_revision})
                    self._catalog.save_annotation(annotation)

                if self._indexer is not None:
                    await self._indexer.index_segment(segment.id)

        await asyncio.gather(*(process_segment(seg) for seg in prepared.segments))

    async def _process_claimed(
        self,
        item: LibraryItem,
        *,
        force_reanalyze: bool = False,
    ) -> None:
        def on_stage(status: LibraryItemStatus) -> None:
            self._store.set_status(item.id, status)

        try:
            prepared = await self._load_or_prepare(item, on_stage)
            source = Path(item.source_path)
            stages: dict[str, Awaitable[object]] = {}
            if self._video_indexer is not None:
                if force_reanalyze:
                    stages["visual"] = self._video_indexer.index_video(
                        prepared.video, source, force=True,
                    )
                else:
                    stages["visual"] = self._video_indexer.index_video(prepared.video, source)
            if self._asr_indexer is not None and prepared.metadata.has_audio:
                stages["asr"] = self._asr_indexer.index_video(
                    prepared.video,
                    source,
                    force=force_reanalyze,
                )
            if self._ocr_indexer is not None:
                stages["ocr"] = self._ocr_indexer.index_video(
                    prepared.video,
                    source,
                    force=force_reanalyze,
                )
            async def run_stage(name: str, operation: Awaitable[object]) -> object:
                started = time.monotonic()
                try:
                    return await operation
                finally:
                    logging.getLogger(__name__).info(
                        "stage=%s video=%s elapsed=%.3fs", name, prepared.video.id,
                        time.monotonic() - started,
                    )

            tasks = [asyncio.create_task(run_stage(name, call)) for name, call in stages.items()]
            group = asyncio.gather(*tasks, return_exceptions=True)
            try:
                results = await asyncio.shield(group)
            except asyncio.CancelledError:
                for task in tasks:
                    task.cancel()
                await group
                self._store.fail(item.id, "解析已中断，可从已保存的片段继续")
                raise
            failures = [f"{name}: {result}" for name, result in zip(stages, results)
                        if isinstance(result, BaseException)]
            if failures:
                raise RuntimeError("; ".join(failures))
            await self._analyze_and_index_segments(
                prepared,
                force_reanalyze=force_reanalyze,
            )
            if self._media_type_annotator is not None:
                try:
                    counts = await self._media_type_annotator.annotate_video(
                        prepared.video.id,
                        force=force_reanalyze,
                    )
                    logging.getLogger(__name__).info(
                        "stage=media_type video=%s annotated=%s",
                        prepared.video.id,
                        counts.get("_annotated", 0),
                    )
                except Exception as exc:  # noqa: BLE001 - media type is best-effort
                    logging.getLogger(__name__).warning(
                        "stage=media_type video=%s failed: %s",
                        prepared.video.id,
                        str(exc)[:500],
                    )
            if self._catalog is not None:
                spans = self._catalog.rebuild_semantic_spans(prepared.video.id)
                logging.getLogger(__name__).info(
                    "stage=semantic_spans video=%s spans=%s",
                    prepared.video.id, spans,
                )
                events, windows = self._catalog.rebuild_timeline_protocol(prepared.video.id)
                logging.getLogger(__name__).info(
                    "stage=timeline_protocol video=%s events=%s windows=%s",
                    prepared.video.id, events, windows,
                )
        except Exception as exc:  # noqa: BLE001 - per-item worker isolation boundary
            error_text = str(exc).strip() or type(exc).__name__
            logging.getLogger(__name__).error(
                "library item=%s parse failed: %s", item.id, error_text[:2000],
            )
            self._store.fail(item.id, error_text)
            return

        self._store.complete(item.id, prepared.video.id)

    def supplement_candidates(self) -> dict[str, int]:
        """增补解析：把失败、中断残留、缺数据的素材放回队列。

        已完成的素材走非 force 增量路径：OCR/ASR/批注/media_type 各自
        跳过已有数据，只补缺失部分；失败和中断残留的会重新尝试。
        """
        from clipatlas.library.models import LibraryItemStatus as S

        summary = {"failed": 0, "interrupted": 0, "incomplete": 0, "total": 0}

        for st, key in ((S.FAILED, "failed"),):
            items = self._store.list_items(status=st, limit=100_000, offset=0)
            for item in items:
                if self._store.retry(item.id):
                    summary[key] += 1

        summary["interrupted"] = self._store.recover_interrupted()

        if self._catalog is not None:
            completed = self._store.list_items(status=S.COMPLETED, limit=100_000, offset=0)
            for item in completed:
                if item.video_id is None:
                    continue
                missing = self._catalog.count_missing_catalog_data(item.video_id)
                if missing > 0 and self._store.requeue_completed(item.id):
                    summary["incomplete"] += 1

        summary["total"] = summary["failed"] + summary["interrupted"] + summary["incomplete"]
        return summary

    async def parse_item(self, item_id: UUID) -> bool:
        if self.operation_lock.locked():
            return False
        async with self.operation_lock:
            item = self._store.claim_item(item_id)
            if item is None:
                return False
            await self._process_claimed(item)
            return True

    async def reparse_item(self, item_id: UUID) -> bool:
        if self.operation_lock.locked():
            return False
        async with self.operation_lock:
            item = self._store.claim_item_for_reparse(item_id)
            if item is None:
                return False
            await self._process_claimed(item, force_reanalyze=True)
            return True

    async def run_once(self) -> bool:
        if self.operation_lock.locked():
            return False
        async with self.operation_lock:
            item = self._store.claim_next()
            if item is None:
                return False
            await self._process_claimed(item)
            return True

import asyncio
from contextlib import suppress
from pathlib import Path
from typing import Protocol
from uuid import UUID

from clipatlas.concurrency import bounded_map
from clipatlas.domain.models import VideoAsset
from clipatlas.ocr.models import OCRFrame, OCRSampleRecord, OCRSampleStatus


class OCRProviderLike(Protocol):
    name: str
    model: str

    async def recognize(self, image_path: Path) -> str: ...


class OCRMaterializerLike(Protocol):
    async def materialize(
        self,
        *,
        source: Path,
        video_id: UUID,
        timestamp_ms: int,
    ) -> OCRFrame: ...


class OCRStoreLike(Protocol):
    def save_sample(self, record: OCRSampleRecord) -> None: ...

    def get_sample(
        self,
        video_id: UUID,
        start_ms: int,
        end_ms: int,
        interval_ms: int,
        provider: str,
        model: str,
        *,
        revision: int,
    ) -> OCRSampleRecord | None: ...

    def get_latest_revision(
        self,
        video_id: UUID,
        provider: str,
        model: str,
        *,
        interval_ms: int,
    ) -> int | None: ...


class OCRIndexer:
    def __init__(
        self,
        *,
        store: OCRStoreLike,
        provider: OCRProviderLike,
        materializer: OCRMaterializerLike,
        interval_ms: int,
        concurrency: int = 1,
    ) -> None:
        if interval_ms <= 0:
            raise ValueError("OCR interval_ms must be positive")
        self._store = store
        self._provider = provider
        self._materializer = materializer
        if concurrency < 1:
            raise ValueError("concurrency must be positive")
        self._concurrency = concurrency
        self._api_slots = asyncio.Semaphore(concurrency)
        self._interval_ms = interval_ms

    async def index_video(
        self,
        video: VideoAsset,
        source: Path,
        *,
        force: bool = False,
    ) -> int:
        duration_ms = video.duration_ms
        if duration_ms is None:
            raise ValueError("video duration is required for OCR indexing")
        latest_revision = self._store.get_latest_revision(
            video.id,
            self._provider.name,
            self._provider.model,
            interval_ms=self._interval_ms,
        )
        if force:
            revision = (latest_revision or 0) + 1
        else:
            revision = latest_revision or 1

        async def index_span(start_ms: int) -> int:
            end_ms = min(start_ms + self._interval_ms, duration_ms)
            existing = self._store.get_sample(
                video.id,
                start_ms,
                end_ms,
                self._interval_ms,
                self._provider.name,
                self._provider.model,
                revision=revision,
            )
            if existing is not None and existing.status is OCRSampleStatus.COMPLETED:
                return 0

            attempt_count = (existing.attempt_count if existing is not None else 0) + 1
            previous_text = existing.text if existing is not None else ""
            self._store.save_sample(
                OCRSampleRecord(
                    video_id=video.id,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    interval_ms=self._interval_ms,
                    provider=self._provider.name,
                    model=self._provider.model,
                    revision=revision,
                    status=OCRSampleStatus.PROCESSING,
                    attempt_count=attempt_count,
                    text=previous_text,
                )
            )

            try:
                frame = await self._materializer.materialize(
                    source=source,
                    video_id=video.id,
                    timestamp_ms=start_ms,
                )
                async with self._api_slots:
                    text = await self._provider.recognize(frame.path)
                self._store.save_sample(
                    OCRSampleRecord(
                        video_id=video.id,
                        start_ms=start_ms,
                        end_ms=end_ms,
                        interval_ms=self._interval_ms,
                        provider=self._provider.name,
                        model=self._provider.model,
                        revision=revision,
                        status=OCRSampleStatus.COMPLETED,
                        attempt_count=attempt_count,
                        text=text,
                    )
                )
                with suppress(OSError):
                    frame.path.unlink(missing_ok=True)
            except Exception as exc:
                self._store.save_sample(
                    OCRSampleRecord(
                        video_id=video.id,
                        start_ms=start_ms,
                        end_ms=end_ms,
                        interval_ms=self._interval_ms,
                        provider=self._provider.name,
                        model=self._provider.model,
                        revision=revision,
                        status=OCRSampleStatus.FAILED,
                        attempt_count=attempt_count,
                        last_error=str(exc)[:2000],
                        text=previous_text,
                    )
                )
                raise

            return 1

        # 采样点过滤：贴尾不足 min_span_ms 的窗口不再生成，
        # 避免在视频末尾出现 5~30ms 碎片窗口导致 FFmpeg 在 EOF 边缘抽帧失败。
        # 首个采样点始终保留（视频再短也要至少抽一帧）。
        min_span_ms = min(1_000, self._interval_ms)
        sampling_starts = [
            start
            for start in range(0, duration_ms, self._interval_ms)
            if start == 0 or duration_ms - start >= min_span_ms
        ]
        processed = await bounded_map(
            sampling_starts, index_span,
            concurrency=self._concurrency + (self._concurrency > 1),
            label=f"ocr video={video.id}",
        )
        return sum(processed)

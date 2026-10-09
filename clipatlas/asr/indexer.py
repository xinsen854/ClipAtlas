import asyncio
from contextlib import suppress
from pathlib import Path
from typing import Protocol
from uuid import UUID

from clipatlas.asr.audio import MAX_ASR_CHUNK_DURATION_MS
from clipatlas.asr.models import (
    ASRAudioChunk,
    ASRChunkRecord,
    ASRChunkStatus,
    ASRSentence,
    ASRWord,
)
from clipatlas.concurrency import bounded_map
from clipatlas.domain.models import VideoAsset
from clipatlas.providers.errors import ProviderRequestError


class ASRProviderLike(Protocol):
    name: str
    model: str

    async def transcribe(self, audio_path: Path) -> list[ASRSentence]: ...


class ASRMaterializerLike(Protocol):
    async def materialize(
        self,
        *,
        source: Path,
        video_id: UUID,
        start_ms: int,
        end_ms: int,
    ) -> ASRAudioChunk: ...


class ASRStoreLike(Protocol):
    def save_asr_chunk(self, record: ASRChunkRecord) -> None: ...

    def get_asr_chunk(
        self,
        video_id: UUID,
        start_ms: int,
        end_ms: int,
        provider: str,
        model: str,
        *,
        revision: int,
    ) -> ASRChunkRecord | None: ...

    def get_latest_asr_revision(
        self,
        video_id: UUID,
        provider: str,
        model: str,
    ) -> int | None: ...


class ASRIndexer:
    def __init__(
        self,
        *,
        store: ASRStoreLike,
        provider: ASRProviderLike,
        materializer: ASRMaterializerLike,
        concurrency: int = 1,
    ) -> None:
        self._store = store
        self._provider = provider
        self._materializer = materializer
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
    ) -> int:
        duration_ms = video.duration_ms
        if duration_ms is None:
            raise ValueError("video duration is required for ASR indexing")
        latest_revision = self._store.get_latest_asr_revision(
            video.id,
            self._provider.name,
            self._provider.model,
        )
        if force:
            revision = (latest_revision or 0) + 1
        else:
            revision = latest_revision or 1

        async def index_span(start_ms: int) -> int:
            end_ms = min(start_ms + MAX_ASR_CHUNK_DURATION_MS, duration_ms)
            existing = self._store.get_asr_chunk(
                video.id,
                start_ms,
                end_ms,
                self._provider.name,
                self._provider.model,
                revision=revision,
            )
            if existing is not None and existing.status is ASRChunkStatus.COMPLETED:
                return 0

            attempt_count = (existing.attempt_count if existing is not None else 0) + 1
            self._store.save_asr_chunk(
                ASRChunkRecord(
                    video_id=video.id,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    provider=self._provider.name,
                    model=self._provider.model,
                    revision=revision,
                    status=ASRChunkStatus.PROCESSING,
                    attempt_count=attempt_count,
                    sentences=existing.sentences if existing is not None else [],
                )
            )

            try:
                chunk = await self._materializer.materialize(
                    source=source,
                    video_id=video.id,
                    start_ms=start_ms,
                    end_ms=end_ms,
                )
                async with self._api_slots:
                    local_sentences = await self._provider.transcribe(chunk.path)
                absolute_sentences = self._shift_sentences(
                    local_sentences,
                    offset_ms=start_ms,
                    chunk_duration_ms=end_ms - start_ms,
                )
                self._store.save_asr_chunk(
                    ASRChunkRecord(
                        video_id=video.id,
                        start_ms=start_ms,
                        end_ms=end_ms,
                        provider=self._provider.name,
                        model=self._provider.model,
                        revision=revision,
                        status=ASRChunkStatus.COMPLETED,
                        attempt_count=attempt_count,
                        sentences=absolute_sentences,
                    )
                )
                with suppress(OSError):
                    chunk.path.unlink(missing_ok=True)
            except Exception as exc:
                self._store.save_asr_chunk(
                    ASRChunkRecord(
                        video_id=video.id,
                        start_ms=start_ms,
                        end_ms=end_ms,
                        provider=self._provider.name,
                        model=self._provider.model,
                        revision=revision,
                        status=ASRChunkStatus.FAILED,
                        attempt_count=attempt_count,
                        last_error=str(exc)[:2000],
                        sentences=existing.sentences if existing is not None else [],
                    )
                )
                raise

            return 1

        processed = await bounded_map(
            range(0, duration_ms, MAX_ASR_CHUNK_DURATION_MS), index_span,
            concurrency=self._concurrency + (self._concurrency > 1),
            label=f"asr video={video.id}",
        )
        return sum(processed)

    @staticmethod
    def _shift_sentences(
        sentences: list[ASRSentence],
        *,
        offset_ms: int,
        chunk_duration_ms: int,
    ) -> list[ASRSentence]:
        shifted: list[ASRSentence] = []
        for sentence in sentences:
            if sentence.end_ms > chunk_duration_ms:
                raise ProviderRequestError("ASR timestamp exceeds the source audio chunk")
            words: list[ASRWord] = []
            for word in sentence.words:
                if word.end_ms > chunk_duration_ms:
                    raise ProviderRequestError("ASR word timestamp exceeds the source audio chunk")
                words.append(
                    word.model_copy(
                        update={
                            "start_ms": word.start_ms + offset_ms,
                            "end_ms": word.end_ms + offset_ms,
                        }
                    )
                )
            shifted.append(
                sentence.model_copy(
                    update={
                        "start_ms": sentence.start_ms + offset_ms,
                        "end_ms": sentence.end_ms + offset_ms,
                        "words": words,
                    }
                )
            )
        return shifted

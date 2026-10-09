import asyncio
from pathlib import Path
from uuid import UUID

import pytest

from clipatlas.catalog.checkpoints import (
    VideoChunkCheckpointStatus,
    VideoChunkCheckpointStore,
)
from clipatlas.catalog.store import CatalogStore
from clipatlas.domain.models import VideoAsset
from clipatlas.embeddings.contracts import EmbeddingVector
from clipatlas.providers.errors import ProviderRequestError
from clipatlas.retrieval.video_indexer import CoarseVideoIndexer
from clipatlas.retrieval.video_profiles import COARSE_30S_PROFILE
from clipatlas.video.chunks import VideoChunkMaterializer, VideoChunkSpan
from clipatlas.video.models import IngestedVideo, MediaMetadata


class RecordingMaterializer(VideoChunkMaterializer):
    def __init__(self) -> None:
        self.calls: list[VideoChunkSpan] = []

    async def materialize(
        self,
        source: Path,
        *,
        video_id: UUID,
        span: VideoChunkSpan,
        chunk_root: Path,
    ) -> Path:
        self.calls.append(span)
        output = chunk_root / str(video_id) / f"{span.start_ms:09d}_{span.end_ms:09d}.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"chunk")
        return output


class RecordingVideoProvider:
    name = "qwen-vl-video"
    model = "qwen3-vl-embedding"
    effective_dimensions = 2560

    def __init__(self, *, fail_once_start_ms: int | None = None) -> None:
        self.calls: list[Path] = []
        self._fail_once_start_ms = fail_once_start_ms
        self._failed = False

    async def embed_video(self, video_path: Path) -> EmbeddingVector:
        self.calls.append(video_path)
        start_ms = int(video_path.stem.split("_", maxsplit=1)[0])
        if self._fail_once_start_ms == start_ms and not self._failed:
            self._failed = True
            raise ProviderRequestError("temporary embedding failure")
        marker = float(len(self.calls))
        return EmbeddingVector(values=[marker] + [0.0] * 2559)

    async def embed_query(self, text: str) -> EmbeddingVector:
        return EmbeddingVector(values=[1.0] + [0.0] * 2559)


def _persist_video(store: CatalogStore, source: Path) -> VideoAsset:
    video = VideoAsset(
        filename=source.name,
        source_uri=source.as_uri(),
        duration_ms=70_000,
        width=1920,
        height=1080,
        fps=25.0,
    )
    store.save_prepared_video(
        IngestedVideo(
            video=video,
            metadata=MediaMetadata(
                duration_ms=70_000,
                width=1920,
                height=1080,
                fps=25.0,
                video_codec="h264",
                has_audio=True,
            ),
            segments=[],
            frames_by_segment={},
        )
    )
    return video


def _coarse_indexer(
    *,
    store: CatalogStore,
    checkpoints: VideoChunkCheckpointStore,
    provider: RecordingVideoProvider,
    materializer: RecordingMaterializer,
    chunk_root: Path,
) -> CoarseVideoIndexer:
    return CoarseVideoIndexer(
        catalog_store=store,
        checkpoint_store=checkpoints,
        provider=provider,
        materializer=materializer,
        chunk_root=chunk_root,
        profile=COARSE_30S_PROFILE,
    )


def _coarse_checkpoint_kwargs() -> dict[str, int]:
    return {
        "chunk_duration_ms": COARSE_30S_PROFILE.chunk_duration_ms,
        "overlap_ms": COARSE_30S_PROFILE.overlap_ms,
    }


@pytest.mark.asyncio
async def test_coarse_indexer_indexes_three_30s_chunks_for_seventy_second_video(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "clipatlas.sqlite3"
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    store = CatalogStore(db_path)
    checkpoints = VideoChunkCheckpointStore(db_path)
    video = _persist_video(store, source)
    materializer = RecordingMaterializer()
    provider = RecordingVideoProvider()
    indexer = _coarse_indexer(
        store=store,
        checkpoints=checkpoints,
        provider=provider,
        materializer=materializer,
        chunk_root=tmp_path / "chunks",
    )

    records = await indexer.index_video(video, source)

    expected_spans = [
        VideoChunkSpan(start_ms=0, end_ms=30_000),
        VideoChunkSpan(start_ms=25_000, end_ms=55_000),
        VideoChunkSpan(start_ms=50_000, end_ms=70_000),
    ]
    assert materializer.calls == expected_spans
    assert [record.start_ms for record in records] == [0, 25_000, 50_000]
    assert [record.end_ms for record in records] == [30_000, 55_000, 70_000]
    assert all(record.provider == provider.name for record in records)
    assert all(record.model == provider.model for record in records)
    assert all(record.dimensions == 2560 for record in records)
    assert all(record.chunk_duration_ms == 30_000 for record in records)
    assert all(record.overlap_ms == 5_000 for record in records)
    assert store.list_video_chunk_embeddings(
        video.id,
        provider=provider.name,
        model=provider.model,
        dimensions=provider.effective_dimensions,
        chunk_duration_ms=COARSE_30S_PROFILE.chunk_duration_ms,
        overlap_ms=COARSE_30S_PROFILE.overlap_ms,
    ) == records
    for span in expected_spans:
        checkpoint = checkpoints.get(
            video.id,
            span.start_ms,
            span.end_ms,
            provider.name,
            provider.model,
            **_coarse_checkpoint_kwargs(),
        )
        assert checkpoint is not None
        assert checkpoint.status is VideoChunkCheckpointStatus.COMPLETED
        assert checkpoint.attempt_count == 1


@pytest.mark.asyncio
async def test_completed_chunk_with_vector_is_skipped_on_retry(tmp_path: Path) -> None:
    db_path = tmp_path / "clipatlas.sqlite3"
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    store = CatalogStore(db_path)
    checkpoints = VideoChunkCheckpointStore(db_path)
    video = _persist_video(store, source)
    materializer = RecordingMaterializer()
    provider = RecordingVideoProvider()
    indexer = _coarse_indexer(
        store=store,
        checkpoints=checkpoints,
        provider=provider,
        materializer=materializer,
        chunk_root=tmp_path / "chunks",
    )

    first = await indexer.index_video(video, source)
    first_materialize_count = len(materializer.calls)
    first_embed_count = len(provider.calls)
    second = await indexer.index_video(video, source)

    assert second == first
    assert len(materializer.calls) == first_materialize_count
    assert len(provider.calls) == first_embed_count

    forced = await indexer.index_video(video, source, force=True)
    assert len(provider.calls) == first_embed_count * 2
    assert len(materializer.calls) == first_materialize_count * 2
    assert forced[0].vector != first[0].vector


@pytest.mark.asyncio
async def test_failed_second_chunk_retries_without_reembedding_completed_first_chunk(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "clipatlas.sqlite3"
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    store = CatalogStore(db_path)
    checkpoints = VideoChunkCheckpointStore(db_path)
    video = _persist_video(store, source)
    materializer = RecordingMaterializer()
    provider = RecordingVideoProvider(fail_once_start_ms=25_000)
    indexer = _coarse_indexer(
        store=store,
        checkpoints=checkpoints,
        provider=provider,
        materializer=materializer,
        chunk_root=tmp_path / "chunks",
    )

    with pytest.raises(ProviderRequestError, match="temporary embedding failure"):
        await indexer.index_video(video, source)

    first_checkpoint = checkpoints.get(
        video.id,
        0,
        30_000,
        provider.name,
        provider.model,
        **_coarse_checkpoint_kwargs(),
    )
    second_checkpoint = checkpoints.get(
        video.id,
        25_000,
        55_000,
        provider.name,
        provider.model,
        **_coarse_checkpoint_kwargs(),
    )
    assert first_checkpoint is not None
    assert first_checkpoint.status is VideoChunkCheckpointStatus.COMPLETED
    assert second_checkpoint is not None
    assert second_checkpoint.status is VideoChunkCheckpointStatus.FAILED
    assert second_checkpoint.attempt_count == 1
    assert second_checkpoint.last_error == "temporary embedding failure"
    calls_before_retry = list(provider.calls)

    records = await indexer.index_video(video, source)

    assert [path.stem for path in calls_before_retry] == [
        "000000000_000030000",
        "000025000_000055000",
    ]
    assert [path.stem for path in provider.calls] == [
        "000000000_000030000",
        "000025000_000055000",
        "000025000_000055000",
        "000050000_000070000",
    ]
    assert [record.start_ms for record in records] == [0, 25_000, 50_000]
    retried = checkpoints.get(
        video.id,
        25_000,
        55_000,
        provider.name,
        provider.model,
        **_coarse_checkpoint_kwargs(),
    )
    assert retried is not None
    assert retried.status is VideoChunkCheckpointStatus.COMPLETED
    assert retried.attempt_count == 2


@pytest.mark.asyncio
async def test_completed_checkpoint_without_vector_is_reprocessed(tmp_path: Path) -> None:
    db_path = tmp_path / "clipatlas.sqlite3"
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    store = CatalogStore(db_path)
    checkpoints = VideoChunkCheckpointStore(db_path)
    video = _persist_video(store, source)
    materializer = RecordingMaterializer()
    provider = RecordingVideoProvider()
    checkpoints.mark_processing(
        video.id,
        0,
        30_000,
        provider.name,
        provider.model,
        **_coarse_checkpoint_kwargs(),
    )
    checkpoints.mark_completed(
        video.id,
        0,
        30_000,
        provider.name,
        provider.model,
        **_coarse_checkpoint_kwargs(),
    )
    indexer = _coarse_indexer(
        store=store,
        checkpoints=checkpoints,
        provider=provider,
        materializer=materializer,
        chunk_root=tmp_path / "chunks",
    )

    await indexer.index_video(video, source)

    assert materializer.calls[0] == VideoChunkSpan(start_ms=0, end_ms=30_000)
    checkpoint = checkpoints.get(
        video.id,
        0,
        30_000,
        provider.name,
        provider.model,
        **_coarse_checkpoint_kwargs(),
    )
    assert checkpoint is not None
    assert checkpoint.status is VideoChunkCheckpointStatus.COMPLETED
    assert checkpoint.attempt_count == 2


@pytest.mark.asyncio
async def test_parallel_visual_calls_preserve_time_order_and_skip_completed(tmp_path):
    source = tmp_path / "video.mp4"
    source.write_bytes(b"fixture")
    catalog = CatalogStore(tmp_path / "library.sqlite3")
    checkpoints = VideoChunkCheckpointStore(tmp_path / "library.sqlite3")
    video = _persist_video(catalog, source)
    ready, release = asyncio.Event(), asyncio.Event()

    class ParallelProvider(RecordingVideoProvider):
        active = 0
        peak = 0

        async def embed_video(self, path):
            self.calls.append(path)
            self.active += 1
            self.peak = max(self.peak, self.active)
            if self.active == 4:
                ready.set()
            await release.wait()
            start = int(path.stem.split("_")[0])
            await asyncio.sleep(0.004 if start == 0 else 0)
            self.active -= 1
            return EmbeddingVector(values=[float(start)] + [0.0] * 2559)

    provider, materializer = ParallelProvider(), RecordingMaterializer()
    indexer = CoarseVideoIndexer(
        catalog_store=catalog, checkpoint_store=checkpoints, provider=provider,
        materializer=materializer, chunk_root=tmp_path / "chunks", concurrency=4,
    )
    task = asyncio.create_task(indexer.index_video(video, source))
    await asyncio.wait_for(ready.wait(), timeout=2)
    await asyncio.sleep(0)
    assert len(materializer.calls) == 5  # four API calls plus one prepared input
    release.set()
    records = await task
    assert provider.peak == 4
    assert [r.start_ms for r in records] == sorted(r.start_ms for r in records)
    assert all(r.vector[0] == r.start_ms for r in records)
    before = len(provider.calls)
    assert await indexer.index_video(video, source) == records
    assert len(provider.calls) == before

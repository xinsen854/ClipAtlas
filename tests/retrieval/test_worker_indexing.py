from pathlib import Path
from uuid import UUID

import pytest

from clipatlas.catalog.checkpoints import PreparedMediaCheckpointStore
from clipatlas.catalog.store import CatalogStore
from clipatlas.domain.models import (
    AnnotationOrigin,
    SegmentSource,
    SemanticAnnotation,
    VideoAsset,
    VideoSegment,
)
from clipatlas.library.models import LibraryItemStatus
from clipatlas.library.store import LibraryStore
from clipatlas.library.worker import SequentialLibraryWorker
from clipatlas.providers.contracts import (
    AnalyzeSegmentRequest,
    AnalyzeSegmentResult,
    ProviderCapabilities,
)
from clipatlas.video.models import IngestedVideo, MediaMetadata


class MappingProcessor:
    def __init__(self, prepared_by_path: dict[Path, IngestedVideo]) -> None:
        self._prepared_by_path = prepared_by_path
        self.calls: list[Path] = []

    async def prepare(self, item_id, source_path, on_stage):
        self.calls.append(source_path)
        on_stage(LibraryItemStatus.PROBING)
        return self._prepared_by_path[source_path]


class RecordingProvider:
    def __init__(self) -> None:
        self.calls: list[UUID] = []

    @property
    def name(self) -> str:
        return "qwen"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(image_input=True, structured_output=True)

    async def analyze_segment(self, request: AnalyzeSegmentRequest) -> AnalyzeSegmentResult:
        self.calls.append(request.segment_id)
        annotation = SemanticAnnotation(
            segment_id=request.segment_id,
            origin=AnnotationOrigin.AI,
            provider=self.name,
            model="qwen3.7-flash",
            description=f"semantic-{request.segment_id}",
            revision=1,
        )
        return AnalyzeSegmentResult(
            provider=self.name,
            model="qwen3.7-flash",
            annotation=annotation,
        )


class FailOnceIndexer:
    def __init__(self, catalog: CatalogStore) -> None:
        self._catalog = catalog
        self.calls: list[UUID] = []
        self.failed = False

    async def index_segment(self, segment_id: UUID) -> bool:
        annotation = self._catalog.get_effective_annotation(segment_id)
        assert annotation is not None, "annotation must be persisted before indexing"
        self.calls.append(segment_id)
        if not self.failed:
            self.failed = True
            raise RuntimeError("temporary embedding failure")
        return True


class SelectiveFailIndexer:
    def __init__(self, fail_segment_id: UUID) -> None:
        self._fail_segment_id = fail_segment_id
        self.calls: list[UUID] = []

    async def index_segment(self, segment_id: UUID) -> bool:
        self.calls.append(segment_id)
        if segment_id == self._fail_segment_id:
            raise RuntimeError("embedding unavailable for this item")
        return True


def _prepared(source: Path) -> IngestedVideo:
    video = VideoAsset(
        filename=source.name,
        source_uri=source.as_uri(),
        duration_ms=4_000,
        width=1280,
        height=720,
        fps=25.0,
    )
    segment = VideoSegment(
        video_id=video.id,
        start_ms=0,
        end_ms=4_000,
        source=SegmentSource.SCENE_DETECTION,
    )
    return IngestedVideo(
        video=video,
        metadata=MediaMetadata(
            duration_ms=4_000,
            width=1280,
            height=720,
            fps=25.0,
            video_codec="h264",
            has_audio=False,
        ),
        segments=[segment],
        frames_by_segment={segment.id: ["file:///cache/frame.jpg"]},
    )


def _queue_source(library: LibraryStore, root_id: UUID, source: Path, fingerprint: str) -> None:
    stat = source.stat()
    library.save_observation(
        root_id,
        source,
        stat.st_size,
        stat.st_mtime_ns,
        fingerprint,
    )


@pytest.mark.asyncio
async def test_embedding_failure_retries_index_only_without_repreparing_or_reanalyzing(
    tmp_path: Path,
) -> None:
    media = tmp_path / "media"
    media.mkdir()
    source = media / "movie.mp4"
    source.write_bytes(b"video")
    db_path = tmp_path / "clipatlas.sqlite3"
    library = LibraryStore(db_path)
    catalog = CatalogStore(db_path)
    checkpoints = PreparedMediaCheckpointStore(db_path)
    root = library.add_root(media)
    _queue_source(library, root.id, source, "fp")
    prepared = _prepared(source)
    processor = MappingProcessor({source: prepared})
    provider = RecordingProvider()
    indexer = FailOnceIndexer(catalog)
    worker = SequentialLibraryWorker(
        store=library,
        processor=processor,
        catalog=catalog,
        provider=provider,
        checkpoints=checkpoints,
        indexer=indexer,
    )

    assert await worker.run_once() is True

    failed = library.get_item_by_path(source)
    assert failed is not None
    assert failed.status is LibraryItemStatus.FAILED
    assert processor.calls == [source]
    assert provider.calls == [prepared.segments[0].id]
    assert indexer.calls == [prepared.segments[0].id]
    assert catalog.has_ai_annotation(prepared.segments[0].id, provider="qwen") is True
    assert checkpoints.get_video_id(failed.id, failed.fingerprint) == prepared.video.id

    assert library.retry(failed.id) is True
    assert await worker.run_once() is True

    completed = library.get_item_by_path(source)
    assert completed is not None
    assert completed.status is LibraryItemStatus.COMPLETED
    assert completed.video_id == prepared.video.id
    assert processor.calls == [source]
    assert provider.calls == [prepared.segments[0].id]
    assert indexer.calls == [prepared.segments[0].id, prepared.segments[0].id]


@pytest.mark.asyncio
async def test_embedding_failure_is_isolated_and_next_queued_video_continues(
    tmp_path: Path,
) -> None:
    media = tmp_path / "media"
    media.mkdir()
    first_source = media / "first.mp4"
    second_source = media / "second.mp4"
    first_source.write_bytes(b"first")
    second_source.write_bytes(b"second")
    db_path = tmp_path / "clipatlas.sqlite3"
    library = LibraryStore(db_path)
    catalog = CatalogStore(db_path)
    checkpoints = PreparedMediaCheckpointStore(db_path)
    root = library.add_root(media)
    _queue_source(library, root.id, first_source, "fp-first")
    _queue_source(library, root.id, second_source, "fp-second")
    first_prepared = _prepared(first_source)
    second_prepared = _prepared(second_source)
    processor = MappingProcessor(
        {
            first_source: first_prepared,
            second_source: second_prepared,
        }
    )
    provider = RecordingProvider()
    indexer = SelectiveFailIndexer(first_prepared.segments[0].id)
    worker = SequentialLibraryWorker(
        store=library,
        processor=processor,
        catalog=catalog,
        provider=provider,
        checkpoints=checkpoints,
        indexer=indexer,
    )

    assert await worker.run_once() is True
    assert await worker.run_once() is True

    first = library.get_item_by_path(first_source)
    second = library.get_item_by_path(second_source)
    assert first is not None and first.status is LibraryItemStatus.FAILED
    assert second is not None and second.status is LibraryItemStatus.COMPLETED
    assert provider.calls == [
        first_prepared.segments[0].id,
        second_prepared.segments[0].id,
    ]
    assert indexer.calls == [
        first_prepared.segments[0].id,
        second_prepared.segments[0].id,
    ]

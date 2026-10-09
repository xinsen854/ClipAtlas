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


class RecordingProcessor:
    def __init__(self, result: IngestedVideo) -> None:
        self.result = result
        self.calls = 0

    async def prepare(self, item_id, source_path, on_stage):
        self.calls += 1
        on_stage(LibraryItemStatus.PROBING)
        on_stage(LibraryItemStatus.SCENE_DETECTION)
        on_stage(LibraryItemStatus.FRAME_EXTRACTION)
        return self.result


class RevisionBlindProvider:
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
            model="qwen-test",
            description=f"ai-call-{len(self.calls)}",
            revision=1,
        )
        return AnalyzeSegmentResult(
            provider=self.name,
            model="qwen-test",
            annotation=annotation,
        )


class RecordingIndexer:
    def __init__(self, catalog: CatalogStore) -> None:
        self.catalog = catalog
        self.effective: list[tuple[UUID, AnnotationOrigin, int, UUID]] = []

    async def index_segment(self, segment_id: UUID) -> bool:
        annotation = self.catalog.get_effective_annotation(segment_id)
        assert annotation is not None
        self.effective.append(
            (segment_id, annotation.origin, annotation.revision, annotation.id)
        )
        return True


def _prepared(source: Path) -> IngestedVideo:
    video = VideoAsset(
        filename=source.name,
        source_uri=source.resolve().as_uri(),
        duration_ms=8_000,
        width=1280,
        height=720,
        fps=25.0,
    )
    first = VideoSegment(
        video_id=video.id,
        start_ms=0,
        end_ms=4_000,
        source=SegmentSource.SCENE_DETECTION,
    )
    second = VideoSegment(
        video_id=video.id,
        start_ms=4_000,
        end_ms=8_000,
        source=SegmentSource.SCENE_DETECTION,
    )
    return IngestedVideo(
        video=video,
        metadata=MediaMetadata(
            duration_ms=8_000,
            width=1280,
            height=720,
            fps=25.0,
            video_codec="h264",
            has_audio=False,
        ),
        segments=[first, second],
        frames_by_segment={
            first.id: ["file:///cache/first.jpg"],
            second.id: ["file:///cache/second.jpg"],
        },
    )


@pytest.mark.asyncio
async def test_reparse_reuses_prepared_media_but_refreshes_every_segment_semantics(
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
    stat = source.stat()
    library.save_observation(root.id, source, stat.st_size, stat.st_mtime_ns, "fp")
    item = library.get_item_by_path(source)
    assert item is not None

    prepared = _prepared(source)
    processor = RecordingProcessor(prepared)
    provider = RevisionBlindProvider()
    indexer = RecordingIndexer(catalog)
    worker = SequentialLibraryWorker(
        store=library,
        processor=processor,
        catalog=catalog,
        provider=provider,
        checkpoints=checkpoints,
        indexer=indexer,
    )

    assert await worker.parse_item(item.id) is True
    completed = library.get_item(item.id)
    assert completed is not None
    assert completed.status is LibraryItemStatus.COMPLETED
    assert completed.attempts == 1
    assert processor.calls == 1
    assert provider.calls == [prepared.segments[0].id, prepared.segments[1].id]

    human = SemanticAnnotation(
        segment_id=prepared.segments[0].id,
        origin=AnnotationOrigin.HUMAN,
        description="human correction",
        revision=1,
    )
    catalog.save_annotation(human)

    assert await worker.reparse_item(item.id) is True

    reparsed = library.get_item(item.id)
    assert reparsed is not None
    assert reparsed.status is LibraryItemStatus.COMPLETED
    assert reparsed.video_id == prepared.video.id
    assert reparsed.attempts == 2
    assert processor.calls == 1
    assert provider.calls == [
        prepared.segments[0].id,
        prepared.segments[1].id,
        prepared.segments[0].id,
        prepared.segments[1].id,
    ]

    for segment in prepared.segments:
        ai_history = catalog.list_annotations(segment.id, origin=AnnotationOrigin.AI)
        assert len(ai_history) == 2
        assert [annotation.revision for annotation in ai_history] == [1, 2]
        assert ai_history[0].id != ai_history[1].id

    first_effective = catalog.get_effective_annotation(prepared.segments[0].id)
    second_effective = catalog.get_effective_annotation(prepared.segments[1].id)
    assert first_effective is not None
    assert second_effective is not None
    assert first_effective.id == human.id
    assert first_effective.origin is AnnotationOrigin.HUMAN
    assert second_effective.origin is AnnotationOrigin.AI
    assert second_effective.revision == 2
    assert indexer.effective[-2:] == [
        (prepared.segments[0].id, AnnotationOrigin.HUMAN, 1, human.id),
        (
            prepared.segments[1].id,
            AnnotationOrigin.AI,
            2,
            second_effective.id,
        ),
    ]

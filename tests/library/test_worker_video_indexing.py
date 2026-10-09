from pathlib import Path
from uuid import UUID

import pytest

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
    def __init__(self, prepared: IngestedVideo) -> None:
        self.prepared = prepared

    async def prepare(self, item_id, source_path: Path, on_stage):
        on_stage(LibraryItemStatus.PROBING)
        on_stage(LibraryItemStatus.SCENE_DETECTION)
        on_stage(LibraryItemStatus.FRAME_EXTRACTION)
        return self.prepared


class RecordingVideoIndexer:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.calls: list[tuple[VideoAsset, Path]] = []

    async def index_video(self, video: VideoAsset, source: Path) -> list[object]:
        self.events.append("video-index")
        self.calls.append((video, source))
        return []


class RecordingUnderstandingProvider:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    @property
    def name(self) -> str:
        return "qwen"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(image_input=True, structured_output=True)

    async def analyze_segment(self, request: AnalyzeSegmentRequest) -> AnalyzeSegmentResult:
        self.events.append("deep-analysis")
        annotation = SemanticAnnotation(
            segment_id=request.segment_id,
            origin=AnnotationOrigin.AI,
            provider=self.name,
            model="gpt-5.6-sol",
            description="deep semantic annotation",
        )
        return AnalyzeSegmentResult(
            provider=self.name,
            model="gpt-5.6-sol",
            annotation=annotation,
        )


def _prepared(source: Path) -> IngestedVideo:
    video = VideoAsset(
        filename=source.name,
        source_uri=source.as_uri(),
        duration_ms=8_000,
        width=1280,
        height=720,
        fps=25.0,
    )
    segment = VideoSegment(
        video_id=video.id,
        start_ms=0,
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
            has_audio=True,
        ),
        segments=[segment],
        frames_by_segment={segment.id: ["file:///cache/frame.jpg"]},
    )


def _queue(store: LibraryStore, root_id: UUID, source: Path) -> None:
    stat = source.stat()
    store.save_observation(
        root_id=root_id,
        source_path=source,
        size_bytes=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        fingerprint="fp",
    )


@pytest.mark.asyncio
async def test_worker_builds_video_index_before_deep_segment_analysis(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    source = media / "movie.mp4"
    source.write_bytes(b"video")
    db_path = tmp_path / "clipatlas.sqlite3"
    library = LibraryStore(db_path)
    catalog = CatalogStore(db_path)
    root = library.add_root(media)
    _queue(library, root.id, source)

    prepared = _prepared(source)
    events: list[str] = []
    video_indexer = RecordingVideoIndexer(events)
    provider = RecordingUnderstandingProvider(events)
    worker = SequentialLibraryWorker(
        store=library,
        processor=RecordingProcessor(prepared),
        catalog=catalog,
        provider=provider,
        video_indexer=video_indexer,
    )

    assert await worker.run_once() is True

    assert events == ["video-index", "deep-analysis"]
    assert video_indexer.calls == [(prepared.video, source)]

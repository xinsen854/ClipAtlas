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


class FailOnceProvider:
    def __init__(self, fail_segment_id: UUID) -> None:
        self.fail_segment_id = fail_segment_id
        self.failed = False
        self.calls: list[UUID] = []

    @property
    def name(self) -> str:
        return "qwen"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(image_input=True, structured_output=True)

    async def analyze_segment(self, request: AnalyzeSegmentRequest) -> AnalyzeSegmentResult:
        self.calls.append(request.segment_id)
        if request.segment_id == self.fail_segment_id and not self.failed:
            self.failed = True
            raise RuntimeError("temporary upstream failure")
        annotation = SemanticAnnotation(
            segment_id=request.segment_id,
            origin=AnnotationOrigin.AI,
            provider=self.name,
            model="qwen3.7-flash",
            description=f"semantic-{request.segment_id}",
            actions=["action"],
            scene=["scene"],
        )
        return AnalyzeSegmentResult(
            provider=self.name,
            model="qwen3.7-flash",
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
async def test_worker_checkpoints_semantics_and_retry_resumes_without_repreparing(
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
    prepared = _prepared(source)
    processor = RecordingProcessor(prepared)
    provider = FailOnceProvider(prepared.segments[1].id)
    worker = SequentialLibraryWorker(
        store=library,
        processor=processor,
        catalog=catalog,
        provider=provider,
        checkpoints=checkpoints,
    )

    assert await worker.run_once() is True

    failed = library.get_item_by_path(source)
    assert failed is not None
    assert failed.status is LibraryItemStatus.FAILED
    assert failed.video_id is None
    assert checkpoints.get_video_id(failed.id, failed.fingerprint) == prepared.video.id
    assert processor.calls == 1
    assert provider.calls == [prepared.segments[0].id, prepared.segments[1].id]
    assert catalog.has_ai_annotation(prepared.segments[0].id, provider="qwen") is True
    assert catalog.has_ai_annotation(prepared.segments[1].id, provider="qwen") is False

    assert library.retry(failed.id) is True
    assert await worker.run_once() is True

    completed = library.get_item_by_path(source)
    assert completed is not None
    assert completed.status is LibraryItemStatus.COMPLETED
    assert completed.video_id == prepared.video.id
    assert processor.calls == 1
    assert provider.calls == [
        prepared.segments[0].id,
        prepared.segments[1].id,
        prepared.segments[1].id,
    ]
    assert catalog.has_ai_annotation(prepared.segments[0].id, provider="qwen") is True
    assert catalog.has_ai_annotation(prepared.segments[1].id, provider="qwen") is True

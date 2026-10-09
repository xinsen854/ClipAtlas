import asyncio
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

import clipatlas.app_state as app_state_module
from clipatlas.catalog.store import CatalogStore
from clipatlas.domain.models import (
    AnnotationOrigin,
    SegmentSource,
    SemanticAnnotation,
    VideoAsset,
    VideoSegment,
)
from clipatlas.library.store import LibraryStore
from clipatlas.library.models import LibraryItemStatus
from clipatlas.library.worker import SequentialLibraryWorker
from clipatlas.providers.contracts import (
    AnalyzeSegmentRequest,
    AnalyzeSegmentResult,
    ProviderCapabilities,
)
from clipatlas.providers.registry import ProviderRegistry
from clipatlas.video.commands import CommandResult
from clipatlas.video.models import IngestedVideo, MediaMetadata


class FakeRunner:
    async def run(self, args: list[str]) -> CommandResult:
        return CommandResult(returncode=0, stdout="", stderr="")


class RecordingProcessor:
    def __init__(self, prepared: IngestedVideo) -> None:
        self.prepared = prepared

    async def prepare(self, item_id: UUID, source_path: Path, on_stage: Any) -> IngestedVideo:
        return self.prepared


class RecordingVideoIndexer:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def index_video(self, video: VideoAsset, source: Path, *, force: bool = False) -> list[object]:
        self.events.append("video-index")
        return []


class RecordingTimedIndexer:
    def __init__(self, events: list[str], name: str) -> None:
        self.events = events
        self.name = name
        self.force_values: list[bool] = []

    async def index_video(
        self,
        video: VideoAsset,
        source: Path,
        *,
        force: bool = False,
    ) -> int:
        self.events.append(self.name)
        self.force_values.append(force)
        return 1


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
        return AnalyzeSegmentResult(
            provider=self.name,
            model="qwen3.8-flash",
            annotation=SemanticAnnotation(
                segment_id=request.segment_id,
                origin=AnnotationOrigin.AI,
                provider=self.name,
                model="qwen3.8-flash",
                description="deep semantic annotation",
            ),
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
        frames_by_segment={segment.id: []},
    )


def _queue(store: LibraryStore, root_id: UUID, source: Path) -> UUID:
    stat = source.stat()
    store.save_observation(
        root_id=root_id,
        source_path=source,
        size_bytes=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        fingerprint="fp",
    )
    item = store.get_item_by_path(source)
    assert item is not None
    return item.id


@pytest.mark.asyncio
async def test_worker_schedules_all_sources_and_reparse_forces_both_timed_indexes(
    tmp_path: Path,
) -> None:
    media = tmp_path / "media"
    media.mkdir()
    source = media / "movie.mp4"
    source.write_bytes(b"video")
    db_path = tmp_path / "library.sqlite3"
    library = LibraryStore(db_path)
    catalog = CatalogStore(db_path)
    root = library.add_root(media)
    item_id = _queue(library, root.id, source)
    prepared = _prepared(source)
    events: list[str] = []
    asr = RecordingTimedIndexer(events, "asr")
    ocr = RecordingTimedIndexer(events, "ocr")
    worker = SequentialLibraryWorker(
        store=library,
        processor=RecordingProcessor(prepared),
        catalog=catalog,
        provider=RecordingUnderstandingProvider(events),
        video_indexer=RecordingVideoIndexer(events),
        asr_indexer=asr,
        ocr_indexer=ocr,
    )

    assert await worker.run_once() is True
    assert events == ["video-index", "asr", "ocr", "deep-analysis"]
    assert asr.force_values == [False]
    assert ocr.force_values == [False]

    events.clear()
    assert await worker.reparse_item(item_id) is True
    assert events == ["video-index", "asr", "ocr", "deep-analysis"]
    assert asr.force_values == [False, True]
    assert ocr.force_values == [False, True]


def test_build_ocr_indexer_uses_formal_bailian_config_and_validates_interval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    class FakeProvider:
        name = "bailian-ocr"
        model = "qwen3.5-ocr"

        def __init__(self, *, api_key: str, base_url: str, client=None, request_policy=None) -> None:
            captured["api_key"] = api_key
            captured["base_url"] = base_url

        async def recognize(self, image_path: Path) -> str:
            return ""

    monkeypatch.setattr(app_state_module, "QwenOCRProvider", FakeProvider)
    monkeypatch.setenv("CLIPATLAS_BAILIAN_API_KEY", "formal-key")
    monkeypatch.setenv(
        "CLIPATLAS_BAILIAN_BASE_URL",
        "https://workspace.cn-beijing.maas.aliyuncs.com/api/v1",
    )
    monkeypatch.setenv("DASHSCOPE_API_KEY", "must-not-be-used")
    monkeypatch.setenv("CLIPATLAS_OCR_INTERVAL_SECONDS", "5")

    indexer = app_state_module.build_ocr_indexer(
        db_path=tmp_path / "library.sqlite3",
        cache_root=tmp_path / "cache",
        runner=FakeRunner(),
    )

    assert indexer is not None
    assert indexer._interval_ms == 5_000
    assert captured == {
        "api_key": "formal-key",
        "base_url": "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    }

    monkeypatch.setenv("CLIPATLAS_OCR_INTERVAL_SECONDS", "0")
    assert (
        app_state_module.build_ocr_indexer(
            db_path=tmp_path / "library.sqlite3",
            cache_root=tmp_path / "cache",
            runner=FakeRunner(),
        )
        is None
    )

    monkeypatch.setenv("CLIPATLAS_OCR_INTERVAL_SECONDS", "2")
    with pytest.raises(ValueError, match="0, 1, 5, or 10"):
        app_state_module.build_ocr_indexer(
            db_path=tmp_path / "library.sqlite3",
            cache_root=tmp_path / "cache",
            runner=FakeRunner(),
        )


def test_ocr_builder_does_not_borrow_legacy_dashscope_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CLIPATLAS_BAILIAN_API_KEY", raising=False)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "legacy-only")
    monkeypatch.setenv(
        "CLIPATLAS_BAILIAN_BASE_URL",
        "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    )
    monkeypatch.setenv("CLIPATLAS_OCR_INTERVAL_SECONDS", "5")

    assert (
        app_state_module.build_ocr_indexer(
            db_path=tmp_path / "library.sqlite3",
            cache_root=tmp_path / "cache",
            runner=FakeRunner(),
        )
        is None
    )


def test_ocr_only_runtime_enables_existing_library_supervisor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLIPATLAS_LIBRARY_DB", str(tmp_path / "library.sqlite3"))
    monkeypatch.setenv("CLIPATLAS_LIBRARY_CACHE_ROOT", str(tmp_path / "cache"))
    monkeypatch.setenv("CLIPATLAS_BAILIAN_API_KEY", "formal-key")
    monkeypatch.setenv(
        "CLIPATLAS_BAILIAN_BASE_URL",
        "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    )
    monkeypatch.setenv("CLIPATLAS_OCR_INTERVAL_SECONDS", "5")
    monkeypatch.setattr(app_state_module, "build_asr_indexer", lambda **kwargs: None)

    runtime = app_state_module.build_library_runtime(ProviderRegistry())

    assert runtime.worker._ocr_indexer is not None
    assert runtime.supervisor.processing_available is True


@pytest.mark.asyncio
async def test_three_stages_overlap_and_one_failure_does_not_abandon_other_stages(tmp_path):
    source = tmp_path / "video.mp4"
    source.write_bytes(b"video")
    store = LibraryStore(tmp_path / "library.sqlite3")
    root = store.add_root(tmp_path)
    item_id = _queue(store, root.id, source)
    started, saved = set(), set()
    all_started, release = asyncio.Event(), asyncio.Event()

    class Stage:
        def __init__(self, name):
            self.name = name

        async def index_video(self, video, source, *, force=False):
            started.add(self.name)
            if len(started) == 3:
                all_started.set()
            await all_started.wait()
            if self.name == "visual":
                raise ValueError("bad tail")
            await release.wait()
            saved.add(self.name)

    worker = SequentialLibraryWorker(
        store=store, processor=RecordingProcessor(_prepared(source)),
        video_indexer=Stage("visual"), asr_indexer=Stage("asr"), ocr_indexer=Stage("ocr"),
    )
    task = asyncio.create_task(worker.run_once())
    await asyncio.wait_for(all_started.wait(), timeout=2)
    assert not task.done()
    assert not await worker.parse_item(item_id)
    release.set()
    assert await task
    assert saved == {"asr", "ocr"}
    assert store.get_item(item_id).status == LibraryItemStatus.FAILED
    assert "visual: bad tail" in store.get_item(item_id).last_error

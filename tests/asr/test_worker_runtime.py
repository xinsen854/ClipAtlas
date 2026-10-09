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
from clipatlas.library.models import LibraryItemStatus
from clipatlas.library.store import LibraryStore
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

    async def index_video(self, video: VideoAsset, source: Path) -> list[object]:
        self.events.append("video-index")
        return []


class RecordingASRIndexer:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.force_values: list[bool] = []

    async def index_video(
        self,
        video: VideoAsset,
        source: Path,
        *,
        force: bool = False,
    ) -> int:
        self.events.append("asr")
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


def _prepared(source: Path, *, has_audio: bool) -> IngestedVideo:
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
            has_audio=has_audio,
        ),
        segments=[segment],
        frames_by_segment={segment.id: []},
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


@pytest.mark.parametrize(
    ("has_audio", "expected"),
    [
        (True, ["video-index", "asr", "deep-analysis"]),
        (False, ["video-index", "deep-analysis"]),
    ],
)
@pytest.mark.asyncio
async def test_worker_runs_asr_between_video_index_and_deep_analysis_only_with_audio(
    tmp_path: Path,
    has_audio: bool,
    expected: list[str],
) -> None:
    media = tmp_path / "media"
    media.mkdir()
    source = media / "movie.mp4"
    source.write_bytes(b"video")
    db_path = tmp_path / "library.sqlite3"
    library = LibraryStore(db_path)
    catalog = CatalogStore(db_path)
    root = library.add_root(media)
    _queue(library, root.id, source)

    events: list[str] = []
    prepared = _prepared(source, has_audio=has_audio)
    asr = RecordingASRIndexer(events)
    worker = SequentialLibraryWorker(
        store=library,
        processor=RecordingProcessor(prepared),
        catalog=catalog,
        provider=RecordingUnderstandingProvider(events),
        video_indexer=RecordingVideoIndexer(events),
        asr_indexer=asr,
    )

    assert await worker.run_once() is True
    assert events == expected
    assert asr.force_values == ([False] if has_audio else [])


def test_build_asr_indexer_uses_only_formal_bailian_config_and_native_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    class FakeProvider:
        name = "bailian-asr"
        model = "qwen-audio-3.0-asr-flash"

        def __init__(self, *, api_key: str, api_root: str, client=None, request_policy=None) -> None:
            captured["api_key"] = api_key
            captured["api_root"] = api_root

        async def transcribe(self, audio_path: Path):
            return []

    monkeypatch.setattr(app_state_module, "QwenAudioASRProvider", FakeProvider)
    monkeypatch.setenv("CLIPATLAS_BAILIAN_API_KEY", "formal-key")
    monkeypatch.setenv(
        "CLIPATLAS_BAILIAN_BASE_URL",
        "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    )
    monkeypatch.setenv("DASHSCOPE_API_KEY", "must-not-be-used")

    indexer = app_state_module.build_asr_indexer(
        db_path=tmp_path / "library.sqlite3",
        cache_root=tmp_path / "cache",
        runner=FakeRunner(),
    )

    assert indexer is not None
    assert captured == {
        "api_key": "formal-key",
        "api_root": "https://workspace.cn-beijing.maas.aliyuncs.com/api/v1",
    }

    monkeypatch.delenv("CLIPATLAS_BAILIAN_API_KEY")
    assert (
        app_state_module.build_asr_indexer(
            db_path=tmp_path / "library.sqlite3",
            cache_root=tmp_path / "cache",
            runner=FakeRunner(),
        )
        is None
    )


def test_library_runtime_injects_asr_without_new_queue_or_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "library.sqlite3"
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("CLIPATLAS_LIBRARY_DB", str(db_path))
    monkeypatch.setenv("CLIPATLAS_LIBRARY_CACHE_ROOT", str(cache_root))
    monkeypatch.setenv("CLIPATLAS_BAILIAN_API_KEY", "formal-key")
    monkeypatch.setenv(
        "CLIPATLAS_BAILIAN_BASE_URL",
        "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    )

    runtime = app_state_module.build_library_runtime(ProviderRegistry())

    assert runtime.worker._asr_indexer is not None
    assert runtime.worker._asr_indexer._store._db_path == db_path.resolve()
    assert runtime.store._db_path == db_path.resolve()
    assert runtime.supervisor.processing_available is True

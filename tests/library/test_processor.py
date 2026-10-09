import asyncio
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname
from uuid import uuid4

import pytest

from clipatlas.library.models import LibraryItemStatus
from clipatlas.library.processor import LocalFilePreparationService
from clipatlas.video.commands import CommandResult
from clipatlas.video.models import MediaMetadata
from clipatlas.video.scenes import SceneRange


class FakeProbe:
    async def probe(self, path: Path) -> MediaMetadata:
        assert path.name == "source.mp4"
        return MediaMetadata(
            duration_ms=5_000,
            width=1920,
            height=1080,
            fps=25.0,
            video_codec="h264",
            has_audio=True,
        )


class FakeSceneDetector:
    def detect(self, path: Path, duration_ms: int) -> list[SceneRange]:
        assert path.name == "source.mp4"
        assert duration_ms == 5_000
        return [
            SceneRange(start_ms=0, end_ms=2_000),
            SceneRange(start_ms=2_000, end_ms=5_000),
        ]


class BlockingSceneDetector(FakeSceneDetector):
    def __init__(self, delay_seconds: float = 0.3) -> None:
        self.delay_seconds = delay_seconds

    def detect(self, path: Path, duration_ms: int) -> list[SceneRange]:
        time.sleep(self.delay_seconds)
        return super().detect(path, duration_ms)


class RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def run(self, args: list[str]) -> CommandResult:
        self.calls.append(args)
        output = Path(args[-1])
        output.write_bytes(b"frame")
        return CommandResult(returncode=0, stdout="", stderr="")


def _uri_path(uri: str) -> Path:
    parsed = urlparse(uri)
    return Path(url2pathname(parsed.path)).resolve()


@pytest.mark.asyncio
async def test_processor_reads_source_in_place_and_writes_only_to_cache(tmp_path: Path) -> None:
    watched = tmp_path / "watched"
    watched.mkdir()
    source = watched / "source.mp4"
    original = b"original-video-bytes"
    source.write_bytes(original)
    cache_root = tmp_path / "cache"
    runner = RecordingRunner()
    stages: list[LibraryItemStatus] = []
    item_id = uuid4()
    service = LocalFilePreparationService(
        probe=FakeProbe(),
        scene_detector=FakeSceneDetector(),
        cache_root=cache_root,
        runner=runner,
    )

    result = await service.prepare(
        item_id=item_id,
        source_path=source,
        on_stage=stages.append,
    )

    assert stages == [
        LibraryItemStatus.PROBING,
        LibraryItemStatus.SCENE_DETECTION,
        LibraryItemStatus.FRAME_EXTRACTION,
    ]
    assert result.video.filename == "source.mp4"
    assert result.video.source_uri == source.resolve().as_uri()
    assert result.video.duration_ms == 5_000
    assert source.read_bytes() == original
    assert not (watched / "frames").exists()
    assert len(result.segments) == 2
    assert len(runner.calls) == 6

    expected_item_cache = (cache_root / str(item_id)).resolve()
    for frame_uris in result.frames_by_segment.values():
        assert len(frame_uris) == 3
        for frame_uri in frame_uris:
            assert _uri_path(frame_uri).is_relative_to(expected_item_cache)
            assert _uri_path(frame_uri).is_file()


@pytest.mark.asyncio
async def test_processor_keeps_event_loop_responsive_during_scene_detection(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    service = LocalFilePreparationService(
        probe=FakeProbe(),
        scene_detector=BlockingSceneDetector(),
        cache_root=tmp_path / "cache",
        runner=RecordingRunner(),
    )

    loop = asyncio.get_running_loop()
    started = loop.time()
    prepare_task = asyncio.create_task(service.prepare(uuid4(), source, lambda _stage: None))

    await asyncio.sleep(0.02)
    elapsed = loop.time() - started

    assert elapsed < 0.15
    await prepare_task


@pytest.mark.asyncio
async def test_processor_creates_clipatlas_owned_video_and_segment_ids(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    service = LocalFilePreparationService(
        probe=FakeProbe(),
        scene_detector=FakeSceneDetector(),
        cache_root=tmp_path / "cache",
        runner=RecordingRunner(),
    )

    result = await service.prepare(uuid4(), source, lambda _stage: None)

    assert all(segment.video_id == result.video.id for segment in result.segments)
    assert len({segment.id for segment in result.segments}) == 2
    assert set(result.frames_by_segment) == {segment.id for segment in result.segments}

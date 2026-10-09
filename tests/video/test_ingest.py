from pathlib import Path
from uuid import UUID

import pytest

from clipatlas.domain.models import SegmentSource
from clipatlas.video.ingest import VideoIngestService
from clipatlas.video.models import MediaMetadata
from clipatlas.video.scenes import SceneRange
from clipatlas.video.storage import StoredVideo


async def _chunks():
    yield b"video-bytes"


class FakeStore:
    def __init__(self, path: Path, events: list[str]) -> None:
        self.path = path
        self.events = events
        self.saved_video_id: UUID | None = None

    async def save(self, video_id, source_name, chunks):
        self.events.append("store")
        self.saved_video_id = video_id
        async for _chunk in chunks:
            pass
        return StoredVideo(video_id=video_id, path=self.path, source_name=source_name)


class FakeProbe:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def probe(self, path):
        self.events.append("probe")
        return MediaMetadata(
            duration_ms=5_000,
            width=1920,
            height=1080,
            fps=25.0,
            video_codec="h264",
            has_audio=True,
        )


class FakeSceneDetector:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def detect(self, path, duration_ms):
        self.events.append("detect")
        return [
            SceneRange(start_ms=0, end_ms=2_000),
            SceneRange(start_ms=2_000, end_ms=5_000),
        ]


class FakeFrameExtractor:
    def __init__(self, events: list[str], root: Path) -> None:
        self.events = events
        self.root = root

    async def extract(self, source, segment_id, start_ms, end_ms):
        self.events.append(f"frame:{start_ms}-{end_ms}")
        return [self.root / f"{segment_id}.jpg"]


@pytest.mark.asyncio
async def test_ingest_orchestrates_media_preparation_and_materializes_segments(tmp_path) -> None:
    events: list[str] = []
    source_path = tmp_path / "stored" / "source.mp4"
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(b"fake")
    store = FakeStore(source_path, events)
    service = VideoIngestService(
        store=store,
        probe=FakeProbe(events),
        scene_detector=FakeSceneDetector(events),
        frame_extractor=FakeFrameExtractor(events, tmp_path / "frames"),
    )

    result = await service.ingest(source_name="original.mp4", chunks=_chunks())

    assert events == ["store", "probe", "detect", "frame:0-2000", "frame:2000-5000"]
    assert store.saved_video_id is not None
    assert result.video.id == store.saved_video_id
    assert result.video.filename == "original.mp4"
    assert result.video.source_uri == source_path.resolve().as_uri()
    assert result.video.duration_ms == 5_000
    assert result.video.width == 1920
    assert result.video.height == 1080
    assert result.video.fps == 25.0
    assert [(item.start_ms, item.end_ms) for item in result.segments] == [
        (0, 2_000),
        (2_000, 5_000),
    ]
    assert all(item.video_id == result.video.id for item in result.segments)
    assert all(item.source is SegmentSource.SCENE_DETECTION for item in result.segments)
    assert set(result.frames_by_segment) == {item.id for item in result.segments}
    for segment in result.segments:
        assert result.frames_by_segment[segment.id] == [
            (tmp_path / "frames" / f"{segment.id}.jpg").resolve().as_uri()
        ]

from uuid import uuid4
import json

import pytest

from clipatlas.video.commands import CommandResult
from clipatlas.video.frames import (
    FrameExtractionError,
    FrameExtractor,
    representative_timestamps,
)


class FakeRunner:
    def __init__(self, result: CommandResult) -> None:
        self.result = result
        self.calls: list[list[str]] = []

    async def run(self, args: list[str]) -> CommandResult:
        self.calls.append(args)
        return self.result


def test_representative_timestamps_use_twenty_fifty_eighty_percent() -> None:
    assert representative_timestamps(1_000, 6_000) == [2_000, 3_500, 5_000]


def test_representative_timestamps_deduplicate_extremely_short_segments() -> None:
    assert representative_timestamps(100, 102) == [100, 101]
    assert representative_timestamps(100, 101) == [100]


@pytest.mark.asyncio
async def test_frame_extractor_creates_deterministic_paths_and_ffmpeg_calls(tmp_path) -> None:
    source = tmp_path / "video" / "source.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"fake")
    segment_id = uuid4()
    runner = FakeRunner(CommandResult(returncode=0, stdout="", stderr=""))
    extractor = FrameExtractor(runner=runner)

    result = await extractor.extract(
        source=source,
        segment_id=segment_id,
        start_ms=1_000,
        end_ms=6_000,
    )

    frame_dir = source.parent / "frames" / str(segment_id)
    expected = [
        frame_dir / "frame_000.jpg",
        frame_dir / "frame_001.jpg",
        frame_dir / "frame_002.jpg",
    ]
    assert result == expected
    assert frame_dir.is_dir()
    manifest = json.loads((frame_dir / "frame_times.json").read_text(encoding="utf-8"))
    assert manifest == {
        "segment_id": str(segment_id), "start_ms": 1000, "end_ms": 6000,
        "frames": [
            {"name": "frame_000.jpg", "timestamp_ms": 2000},
            {"name": "frame_001.jpg", "timestamp_ms": 3500},
            {"name": "frame_002.jpg", "timestamp_ms": 5000},
        ],
    }
    assert runner.calls == [
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-ss",
            "2.000",
            "-i",
            str(source),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(expected[0]),
        ],
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-ss",
            "3.500",
            "-i",
            str(source),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(expected[1]),
        ],
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-ss",
            "5.000",
            "-i",
            str(source),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(expected[2]),
        ],
    ]


@pytest.mark.asyncio
async def test_frame_extractor_normalizes_ffmpeg_failure(tmp_path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"fake")
    runner = FakeRunner(CommandResult(returncode=1, stdout="", stderr="decode failed"))
    extractor = FrameExtractor(runner=runner)

    with pytest.raises(FrameExtractionError, match="ffmpeg failed"):
        await extractor.extract(
            source=source,
            segment_id=uuid4(),
            start_ms=0,
            end_ms=1_000,
        )

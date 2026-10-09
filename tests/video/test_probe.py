import json
from pathlib import Path

import pytest

from clipatlas.video.commands import CommandResult
from clipatlas.video.probe import MediaProbe, MediaProbeError


class FakeRunner:
    def __init__(self, result: CommandResult) -> None:
        self.result = result
        self.calls: list[list[str]] = []

    async def run(self, args: list[str]) -> CommandResult:
        self.calls.append(args)
        return self.result


@pytest.mark.asyncio
async def test_probe_parses_video_metadata_and_audio_presence() -> None:
    payload = {
        "format": {"duration": "12.3456"},
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "30000/1001",
            },
            {"codec_type": "audio", "codec_name": "aac"},
        ],
    }
    runner = FakeRunner(CommandResult(returncode=0, stdout=json.dumps(payload), stderr=""))
    probe = MediaProbe(runner=runner)

    result = await probe.probe(Path("/tmp/example.mp4"))

    assert result.duration_ms == 12_346
    assert result.width == 1920
    assert result.height == 1080
    assert result.fps == pytest.approx(29.97002997)
    assert result.video_codec == "h264"
    assert result.has_audio is True
    assert runner.calls == [
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(Path("/tmp/example.mp4")),
        ]
    ]


@pytest.mark.asyncio
async def test_probe_rejects_output_without_video_stream() -> None:
    payload = {
        "format": {"duration": "5.0"},
        "streams": [{"codec_type": "audio", "codec_name": "aac"}],
    }
    runner = FakeRunner(CommandResult(returncode=0, stdout=json.dumps(payload), stderr=""))
    probe = MediaProbe(runner=runner)

    with pytest.raises(MediaProbeError, match="video stream"):
        await probe.probe(Path("/tmp/audio-only.m4a"))


@pytest.mark.asyncio
async def test_probe_normalizes_ffprobe_failure() -> None:
    runner = FakeRunner(
        CommandResult(returncode=1, stdout="", stderr="Invalid data found when processing input")
    )
    probe = MediaProbe(runner=runner)

    with pytest.raises(MediaProbeError, match="ffprobe failed"):
        await probe.probe(Path("/tmp/broken.mp4"))

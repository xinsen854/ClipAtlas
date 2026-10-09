from pathlib import Path

import pytest

from clipatlas.speech.audio import AudioNormalizer
from clipatlas.video.commands import CommandResult


class RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def run(self, args: list[str]) -> CommandResult:
        self.calls.append(args)
        Path(args[-1]).parent.mkdir(parents=True, exist_ok=True)
        Path(args[-1]).write_bytes(b"wav")
        return CommandResult(returncode=0, stdout="", stderr="")


@pytest.mark.asyncio
async def test_extract_materializes_exact_pcm_story_audio_window(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(b"source")
    destination = tmp_path / "parts" / "narration.wav"
    runner = RecordingRunner()
    normalizer = AudioNormalizer(runner=runner)

    result = await normalizer.extract(
        source,
        destination,
        start_ms=1250,
        end_ms=3500,
    )

    assert result == destination
    assert runner.calls == [[
        "ffmpeg",
        "-y",
        "-ss",
        "1.250",
        "-i",
        str(source),
        "-t",
        "2.250",
        "-vn",
        "-ac",
        "1",
        "-ar",
        "48000",
        "-c:a",
        "pcm_s16le",
        str(destination),
    ]]


@pytest.mark.asyncio
async def test_silence_materializes_exact_pcm_story_gap(tmp_path: Path) -> None:
    destination = tmp_path / "parts" / "silence.wav"
    runner = RecordingRunner()
    normalizer = AudioNormalizer(runner=runner)

    result = await normalizer.silence(destination, duration_ms=3000)

    assert result == destination
    assert runner.calls == [[
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=48000:cl=mono",
        "-t",
        "3.000",
        "-c:a",
        "pcm_s16le",
        str(destination),
    ]]

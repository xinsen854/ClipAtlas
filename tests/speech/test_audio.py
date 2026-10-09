from pathlib import Path

import pytest

from clipatlas.speech.audio import AudioNormalizer
from clipatlas.speech.errors import SpeechAudioValidationError
from clipatlas.video.commands import CommandResult


class RecordingRunner:
    def __init__(self, *, fail_program: str | None = None) -> None:
        self.calls: list[list[str]] = []
        self.fail_program = fail_program

    async def run(self, args: list[str]) -> CommandResult:
        self.calls.append(args)
        if self.fail_program == args[0]:
            return CommandResult(returncode=1, stdout="", stderr="command failed")
        if args[0] == "ffprobe":
            return CommandResult(returncode=0, stdout="1.234\n", stderr="")
        Path(args[-1]).write_bytes(b"wav")
        return CommandResult(returncode=0, stdout="", stderr="")


@pytest.mark.asyncio
async def test_normalize_uses_canonical_pcm_wav_settings(tmp_path: Path) -> None:
    source = tmp_path / "source.mp3"
    source.write_bytes(b"audio")
    destination = tmp_path / "out" / "track.wav"
    runner = RecordingRunner()
    normalizer = AudioNormalizer(runner=runner)

    result = await normalizer.normalize(source, destination)

    assert result == destination
    assert destination.exists()
    assert runner.calls == [
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            "-ar",
            "48000",
            "-c:a",
            "pcm_s16le",
            str(destination),
        ]
    ]


@pytest.mark.asyncio
async def test_probe_duration_converts_seconds_to_integer_milliseconds(tmp_path: Path) -> None:
    source = tmp_path / "track.wav"
    source.write_bytes(b"audio")
    runner = RecordingRunner()
    normalizer = AudioNormalizer(runner=runner)

    duration_ms = await normalizer.probe_duration_ms(source)

    assert duration_ms == 1234
    assert runner.calls[0][0] == "ffprobe"
    assert str(source) == runner.calls[0][-1]


@pytest.mark.asyncio
async def test_concat_uses_controlled_manifest_and_rejects_missing_inputs(tmp_path: Path) -> None:
    first = tmp_path / "units" / "0001.wav"
    second = tmp_path / "units" / "0002.wav"
    first.parent.mkdir(parents=True)
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    destination = tmp_path / "track" / "track.wav"
    runner = RecordingRunner()
    normalizer = AudioNormalizer(runner=runner)

    result = await normalizer.concat([first, second], destination)

    assert result == destination
    call = runner.calls[0]
    assert call[0] == "ffmpeg"
    assert call[1:4] == ["-y", "-f", "concat"]
    assert call[4:7] == ["-safe", "0", "-i"]
    manifest = Path(call[7])
    assert manifest.parent == destination.parent
    manifest_text = manifest.read_text(encoding="utf-8")
    assert str(first.resolve()).replace("'", "'\\''") in manifest_text
    assert str(second.resolve()).replace("'", "'\\''") in manifest_text

    with pytest.raises(SpeechAudioValidationError, match="does not exist"):
        await normalizer.concat([tmp_path / "missing.wav"], destination)


@pytest.mark.asyncio
async def test_audio_command_failure_is_normalized(tmp_path: Path) -> None:
    source = tmp_path / "source.mp3"
    source.write_bytes(b"audio")
    normalizer = AudioNormalizer(runner=RecordingRunner(fail_program="ffmpeg"))

    with pytest.raises(SpeechAudioValidationError, match="command failed"):
        await normalizer.normalize(source, tmp_path / "out.wav")


@pytest.mark.asyncio
async def test_probe_rejects_invalid_or_non_positive_duration(tmp_path: Path) -> None:
    source = tmp_path / "track.wav"
    source.write_bytes(b"audio")

    class InvalidProbeRunner:
        async def run(self, args: list[str]) -> CommandResult:
            return CommandResult(returncode=0, stdout="not-a-number", stderr="")

    with pytest.raises(SpeechAudioValidationError, match="invalid duration"):
        await AudioNormalizer(runner=InvalidProbeRunner()).probe_duration_ms(source)

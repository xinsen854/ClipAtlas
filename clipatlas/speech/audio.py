import math
from pathlib import Path

from clipatlas.speech.errors import SpeechAudioValidationError
from clipatlas.video.commands import AsyncCommandRunner, SubprocessCommandRunner


class AudioNormalizer:
    def __init__(self, runner: AsyncCommandRunner | None = None) -> None:
        self._runner = runner or SubprocessCommandRunner()

    @staticmethod
    def _require_source(path: Path) -> None:
        if not path.is_file():
            raise SpeechAudioValidationError(f"Audio source does not exist: {path}")

    async def normalize(
        self,
        source: Path,
        destination: Path,
        sample_rate: int = 48_000,
    ) -> Path:
        self._require_source(source)
        if sample_rate <= 0:
            raise SpeechAudioValidationError("sample_rate must be positive")
        destination.parent.mkdir(parents=True, exist_ok=True)
        result = await self._runner.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(source),
                "-ar",
                str(sample_rate),
                "-c:a",
                "pcm_s16le",
                str(destination),
            ]
        )
        if result.returncode != 0:
            raise SpeechAudioValidationError(
                result.stderr.strip() or "ffmpeg audio normalization failed"
            )
        if not destination.is_file():
            raise SpeechAudioValidationError("ffmpeg reported success but produced no audio")
        return destination

    async def extract(
        self,
        source: Path,
        destination: Path,
        *,
        start_ms: int,
        end_ms: int,
        sample_rate: int = 48_000,
    ) -> Path:
        self._require_source(source)
        if start_ms < 0 or end_ms <= start_ms:
            raise SpeechAudioValidationError("end_ms must be greater than start_ms")
        if sample_rate <= 0:
            raise SpeechAudioValidationError("sample_rate must be positive")
        destination.parent.mkdir(parents=True, exist_ok=True)
        result = await self._runner.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                f"{start_ms / 1000:.3f}",
                "-i",
                str(source),
                "-t",
                f"{(end_ms - start_ms) / 1000:.3f}",
                "-vn",
                "-ac",
                "1",
                "-ar",
                str(sample_rate),
                "-c:a",
                "pcm_s16le",
                str(destination),
            ]
        )
        if result.returncode != 0:
            raise SpeechAudioValidationError(
                result.stderr.strip() or "ffmpeg audio extraction failed"
            )
        if not destination.is_file():
            raise SpeechAudioValidationError("ffmpeg reported success but produced no audio")
        return destination

    async def silence(
        self,
        destination: Path,
        *,
        duration_ms: int,
        sample_rate: int = 48_000,
    ) -> Path:
        if duration_ms <= 0:
            raise SpeechAudioValidationError("duration_ms must be positive")
        if sample_rate <= 0:
            raise SpeechAudioValidationError("sample_rate must be positive")
        destination.parent.mkdir(parents=True, exist_ok=True)
        result = await self._runner.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"anullsrc=r={sample_rate}:cl=mono",
                "-t",
                f"{duration_ms / 1000:.3f}",
                "-c:a",
                "pcm_s16le",
                str(destination),
            ]
        )
        if result.returncode != 0:
            raise SpeechAudioValidationError(
                result.stderr.strip() or "ffmpeg silence generation failed"
            )
        if not destination.is_file():
            raise SpeechAudioValidationError("ffmpeg reported success but produced no audio")
        return destination

    async def probe_duration_ms(self, source: Path) -> int:
        self._require_source(source)
        result = await self._runner.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(source),
            ]
        )
        if result.returncode != 0:
            raise SpeechAudioValidationError(
                result.stderr.strip() or "ffprobe audio duration failed"
            )
        try:
            seconds = float(result.stdout.strip())
        except ValueError as exc:
            raise SpeechAudioValidationError("ffprobe returned invalid duration") from exc
        if not math.isfinite(seconds) or seconds <= 0:
            raise SpeechAudioValidationError("ffprobe returned invalid duration")
        return round(seconds * 1000)

    @staticmethod
    def _manifest_line(path: Path) -> str:
        escaped = str(path.resolve()).replace("'", "'\\''")
        return f"file '{escaped}'\n"

    async def concat(self, inputs: list[Path], destination: Path) -> Path:
        if not inputs:
            raise SpeechAudioValidationError("At least one audio input is required")
        for source in inputs:
            self._require_source(source)

        destination.parent.mkdir(parents=True, exist_ok=True)
        manifest = destination.parent / "concat.txt"
        manifest.write_text(
            "".join(self._manifest_line(source) for source in inputs),
            encoding="utf-8",
        )
        result = await self._runner.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(manifest),
                "-c",
                "copy",
                str(destination),
            ]
        )
        if result.returncode != 0:
            raise SpeechAudioValidationError(
                result.stderr.strip() or "ffmpeg audio concatenation failed"
            )
        if not destination.is_file():
            raise SpeechAudioValidationError("ffmpeg reported success but produced no audio")
        return destination

from pathlib import Path
from uuid import UUID

from clipatlas.ocr.models import OCRFrame
from clipatlas.video.commands import AsyncCommandRunner, SubprocessCommandRunner


class OCRFrameMaterializer:
    def __init__(
        self,
        root: Path,
        *,
        runner: AsyncCommandRunner | None = None,
    ) -> None:
        self._root = root.resolve()
        self._runner = runner or SubprocessCommandRunner()

    async def materialize(
        self,
        *,
        source: Path,
        video_id: UUID,
        timestamp_ms: int,
    ) -> OCRFrame:
        source = source.resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        if timestamp_ms < 0:
            raise ValueError("OCR frame timestamp must be non-negative")

        frame_dir = self._root / str(video_id)
        frame_dir.mkdir(parents=True, exist_ok=True)
        destination = frame_dir / f"{timestamp_ms:012d}.jpg"
        if destination.is_file() and destination.stat().st_size > 0:
            return OCRFrame(timestamp_ms=timestamp_ms, path=destination)

        command = [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-ss",
                f"{timestamp_ms / 1000:.3f}",
                "-i",
                str(source),
                "-frames:v",
                "1",
                "-q:v",
                "3",
                str(destination),
            ]
        result = await self._runner.run(command)
        if result.returncode != 0 and "Non full-range YUV" in result.stderr:
            # FFmpeg 8 rejects the default MJPEG conversion for this input.
            # Retry with the legacy JPEG pixel range, keeping the normal path
            # byte-for-byte compatible for other media and test doubles.
            result = await self._runner.run(command[:-1] + ["-pix_fmt", "yuvj420p", command[-1]])
        if result.returncode != 0:
            detail = result.stderr.strip() or "unknown ffmpeg error"
            raise RuntimeError(f"OCR frame extraction failed: {detail}")
        if not destination.is_file() or destination.stat().st_size <= 0:
            raise RuntimeError("OCR frame extraction produced no image")
        return OCRFrame(timestamp_ms=timestamp_ms, path=destination)

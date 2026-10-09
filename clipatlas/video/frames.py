from pathlib import Path
import json
from uuid import UUID

from clipatlas.video.commands import AsyncCommandRunner, SubprocessCommandRunner


class FrameExtractionError(RuntimeError):
    """Raised when ffmpeg cannot extract a representative frame."""


def representative_timestamps(start_ms: int, end_ms: int) -> list[int]:
    if start_ms < 0:
        raise ValueError("start_ms must be non-negative")
    if end_ms <= start_ms:
        raise ValueError("end_ms must be greater than start_ms")

    duration_ms = end_ms - start_ms
    timestamps: list[int] = []
    for ratio in (0.2, 0.5, 0.8):
        timestamp = start_ms + round(duration_ms * ratio)
        timestamp = min(max(timestamp, start_ms), end_ms - 1)
        if not timestamps or timestamp != timestamps[-1]:
            timestamps.append(timestamp)
    return timestamps


class FrameExtractor:
    def __init__(self, runner: AsyncCommandRunner | None = None) -> None:
        self._runner = runner or SubprocessCommandRunner()

    async def extract(
        self,
        source: Path,
        segment_id: UUID,
        start_ms: int,
        end_ms: int,
        frame_root: Path | None = None,
    ) -> list[Path]:
        timestamps = representative_timestamps(start_ms, end_ms)
        root = frame_root if frame_root is not None else source.parent / "frames"
        frame_dir = root / str(segment_id)
        frame_dir.mkdir(parents=True, exist_ok=True)

        outputs: list[Path] = []
        for index, timestamp_ms in enumerate(timestamps):
            output = frame_dir / f"frame_{index:03d}.jpg"
            args = [
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
                "2",
                str(output),
            ]
            result = await self._runner.run(args)
            if result.returncode != 0:
                detail = result.stderr.strip() or "unknown ffmpeg error"
                raise FrameExtractionError(f"ffmpeg failed: {detail}")
            outputs.append(output)
        (frame_dir / "frame_times.json").write_text(json.dumps({
            "segment_id": str(segment_id), "start_ms": start_ms, "end_ms": end_ms,
            "frames": [{"name": path.name, "timestamp_ms": timestamp}
                       for path, timestamp in zip(outputs, timestamps, strict=True)],
        }), encoding="utf-8")
        return outputs

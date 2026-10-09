from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from clipatlas.video.commands import AsyncCommandRunner, SubprocessCommandRunner

# The 24 KB minimum is 24 KiB: a 24,181-byte tail was rejected upstream.
DASHSCOPE_MIN_VIDEO_BYTES = 24 * 1024
DASHSCOPE_MAX_VIDEO_BYTES = 50_700_000


@dataclass(frozen=True, slots=True)
class VideoChunkSpan:
    start_ms: int
    end_ms: int


class VideoChunkMaterializationError(RuntimeError):
    """Raised when ffmpeg cannot create a DashScope-ready video chunk."""


class VideoChunkTooSmallError(VideoChunkMaterializationError):
    """The chunk is smaller than the upstream minimum even as a raw copy.

    Such a chunk cannot be uploaded to DashScope at all; callers should skip
    the span instead of failing the whole video.
    """


class VideoChunkMaterializer:
    """Materialize upload-safe chunks using the SentrySearch-tested media flow.

    The flow intentionally mirrors the PoC behavior that proved reliable with
    qwen3-vl-embedding: first isolate the requested source range with stream
    copy, then downscale/reduce FPS and keep a small AAC track. The final file
    is checked against DashScope's documented upload-size gate before it is
    ever handed to the embedding provider.
    """

    def __init__(self, runner: AsyncCommandRunner | None = None) -> None:
        self._runner = runner or SubprocessCommandRunner()

    async def materialize(
        self,
        source: Path,
        *,
        video_id: UUID,
        span: VideoChunkSpan,
        chunk_root: Path,
    ) -> Path:
        if not source.is_file():
            raise FileNotFoundError(f"Video source not found: {source}")
        if span.start_ms < 0 or span.end_ms <= span.start_ms:
            raise ValueError("chunk span must be a positive ordered range")

        output_dir = chunk_root / str(video_id)
        output_dir.mkdir(parents=True, exist_ok=True)
        stem = f"{span.start_ms:09d}_{span.end_ms:09d}"
        raw_output = output_dir / f"{stem}_source.mp4"
        output = output_dir / f"{stem}.mp4"
        duration_ms = span.end_ms - span.start_ms

        await self._run_ffmpeg(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-ss",
                f"{span.start_ms / 1000:.3f}",
                "-i",
                str(source),
                "-t",
                f"{duration_ms / 1000:.3f}",
                "-c",
                "copy",
                str(raw_output),
            ]
        )
        await self._run_ffmpeg(
            self._preprocess_args(
                raw_output,
                output,
                resolution=480,
                fps=5,
                crf=28,
                audio_bitrate="64k",
            )
        )

        prepared_size = self._file_size(output)
        raw_size = self._file_size(raw_output)
        if self._within_upload_limits(prepared_size):
            raw_output.unlink(missing_ok=True)
            return output

        if prepared_size < DASHSCOPE_MIN_VIDEO_BYTES:
            if self._within_upload_limits(raw_size):
                output.unlink(missing_ok=True)
                return raw_output
            raise self._too_small_error(prepared_size=prepared_size, raw_size=raw_size)

        await self._run_ffmpeg(
            self._preprocess_args(
                raw_output,
                output,
                resolution=360,
                fps=3,
                crf=32,
                audio_bitrate="48k",
            )
        )
        retry_size = self._file_size(output)
        if self._within_upload_limits(retry_size):
            raw_output.unlink(missing_ok=True)
            return output
        if self._within_upload_limits(raw_size):
            output.unlink(missing_ok=True)
            return raw_output
        raise self._too_small_error(prepared_size=retry_size, raw_size=raw_size)

    async def _run_ffmpeg(self, args: list[str]) -> None:
        result = await self._runner.run(args)
        if result.returncode != 0:
            detail = result.stderr.strip() or "unknown ffmpeg error"
            raise VideoChunkMaterializationError(f"ffmpeg failed: {detail}")

    @staticmethod
    def _preprocess_args(
        source: Path,
        output: Path,
        *,
        resolution: int,
        fps: int,
        crf: int,
        audio_bitrate: str,
    ) -> list[str]:
        return [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(source),
            "-vf",
            f"scale=-2:{resolution},fps={fps}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            str(crf),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            audio_bitrate,
            str(output),
        ]

    @staticmethod
    def _file_size(path: Path) -> int:
        try:
            return path.stat().st_size
        except FileNotFoundError as exc:
            raise VideoChunkMaterializationError(
                f"ffmpeg did not create expected chunk: {path}"
            ) from exc

    @staticmethod
    def _within_upload_limits(size: int) -> bool:
        return DASHSCOPE_MIN_VIDEO_BYTES <= size <= DASHSCOPE_MAX_VIDEO_BYTES

    @staticmethod
    def _size_error(*, prepared_size: int, raw_size: int) -> VideoChunkMaterializationError:
        return VideoChunkMaterializationError(
            "video chunk cannot satisfy DashScope upload limits "
            f"[{DASHSCOPE_MIN_VIDEO_BYTES}, {DASHSCOPE_MAX_VIDEO_BYTES}] bytes; "
            f"prepared={prepared_size}, source_chunk={raw_size}"
        )

    @staticmethod
    def _too_small_error(*, prepared_size: int, raw_size: int) -> VideoChunkTooSmallError:
        return VideoChunkTooSmallError(
            "video chunk is smaller than the DashScope minimum even as a raw copy "
            f"[{DASHSCOPE_MIN_VIDEO_BYTES} bytes minimum]; "
            f"prepared={prepared_size}, source_chunk={raw_size}"
        )


def plan_video_chunks(
    duration_ms: int,
    *,
    chunk_duration_ms: int = 30_000,
    overlap_ms: int = 5_000,
) -> list[VideoChunkSpan]:
    """Plan deterministic overlapping video chunk spans without touching media files."""
    if duration_ms <= 0:
        raise ValueError("duration_ms must be greater than zero")
    if chunk_duration_ms <= 0:
        raise ValueError("chunk_duration_ms must be greater than zero")
    if overlap_ms < 0:
        raise ValueError("overlap_ms must not be negative")
    if overlap_ms >= chunk_duration_ms:
        raise ValueError("overlap_ms must be smaller than chunk_duration_ms")

    if duration_ms <= chunk_duration_ms:
        return [VideoChunkSpan(start_ms=0, end_ms=duration_ms)]

    step_ms = chunk_duration_ms - overlap_ms
    spans: list[VideoChunkSpan] = []
    start_ms = 0

    while start_ms < duration_ms:
        end_ms = min(start_ms + chunk_duration_ms, duration_ms)
        spans.append(VideoChunkSpan(start_ms=start_ms, end_ms=end_ms))
        if end_ms >= duration_ms:
            break
        start_ms += step_ms

    return spans

from pathlib import Path
from uuid import UUID

from clipatlas.asr.models import ASRAudioChunk
from clipatlas.video.commands import AsyncCommandRunner, SubprocessCommandRunner


MAX_ASR_CHUNK_DURATION_MS = 225_000


class ASRAudioChunkMaterializer:
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
        start_ms: int,
        end_ms: int,
    ) -> ASRAudioChunk:
        source = source.resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        if start_ms < 0 or end_ms <= start_ms:
            raise ValueError("ASR chunk range must be positive and ordered")
        if end_ms - start_ms > MAX_ASR_CHUNK_DURATION_MS:
            raise ValueError("ASR chunk duration exceeds the 225 second limit")

        destination_dir = self._root / str(video_id)
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / f"{start_ms:012d}-{end_ms:012d}.wav"
        if destination.is_file() and destination.stat().st_size > 0:
            return ASRAudioChunk(start_ms=start_ms, end_ms=end_ms, path=destination)

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
                "16000",
                "-c:a",
                "pcm_s16le",
                str(destination),
            ]
        )
        if result.returncode != 0:
            raise RuntimeError(f"ASR audio extraction failed: {result.stderr.strip()}")
        if not destination.is_file() or destination.stat().st_size <= 0:
            raise RuntimeError("ASR audio extraction produced no audio")
        return ASRAudioChunk(start_ms=start_ms, end_ms=end_ms, path=destination)

from pathlib import Path
from uuid import uuid4

import pytest

import clipatlas.video.chunks as chunks_module
from clipatlas.video.chunks import (
    VideoChunkMaterializationError,
    VideoChunkMaterializer,
    VideoChunkSpan,
    VideoChunkTooSmallError,
)
from clipatlas.video.commands import CommandResult


class MaterializingRunner:
    def __init__(
        self,
        *,
        sizes: list[int] | None = None,
        result: CommandResult | None = None,
    ) -> None:
        self.calls: list[list[str]] = []
        self._sizes = sizes or [100, 40, 40]
        self._result = result or CommandResult(returncode=0, stdout="", stderr="")

    async def run(self, args: list[str]) -> CommandResult:
        self.calls.append(args)
        if self._result.returncode == 0:
            output = Path(args[-1])
            output.parent.mkdir(parents=True, exist_ok=True)
            index = min(len(self.calls) - 1, len(self._sizes) - 1)
            output.write_bytes(b"x" * self._sizes[index])
        return self._result


@pytest.fixture(autouse=True)
def small_dashscope_size_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chunks_module, "DASHSCOPE_MIN_VIDEO_BYTES", 24)
    monkeypatch.setattr(chunks_module, "DASHSCOPE_MAX_VIDEO_BYTES", 1000)


@pytest.mark.asyncio
async def test_materializer_uses_sentrysearch_style_chunk_then_preprocess(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    cache_root = tmp_path / "cache"
    video_id = uuid4()
    runner = MaterializingRunner(sizes=[100, 40])
    materializer = VideoChunkMaterializer(runner=runner)

    output = await materializer.materialize(
        source,
        video_id=video_id,
        span=VideoChunkSpan(start_ms=25_000, end_ms=55_000),
        chunk_root=cache_root,
    )

    assert output == cache_root / str(video_id) / "000025000_000055000.mp4"
    assert len(runner.calls) == 2

    raw_args, preprocess_args = runner.calls
    assert raw_args == [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-ss",
        "25.000",
        "-i",
        str(source),
        "-t",
        "30.000",
        "-c",
        "copy",
        str(cache_root / str(video_id) / "000025000_000055000_source.mp4"),
    ]
    assert preprocess_args == [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-i",
        str(cache_root / str(video_id) / "000025000_000055000_source.mp4"),
        "-vf",
        "scale=-2:480,fps=5",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "28",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "64k",
        str(output),
    ]
    assert output.parent.is_dir()
    assert not (source.parent / str(video_id)).exists()


@pytest.mark.asyncio
async def test_materializer_uses_exact_final_chunk_duration(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    runner = MaterializingRunner()
    materializer = VideoChunkMaterializer(runner=runner)

    await materializer.materialize(
        source,
        video_id=uuid4(),
        span=VideoChunkSpan(start_ms=50_000, end_ms=70_000),
        chunk_root=tmp_path / "cache",
    )

    raw_args = runner.calls[0]
    assert raw_args[raw_args.index("-ss") + 1] == "50.000"
    assert raw_args[raw_args.index("-t") + 1] == "20.000"


@pytest.mark.asyncio
async def test_materializer_falls_back_to_source_chunk_when_preprocessed_is_too_small(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    runner = MaterializingRunner(sizes=[100, 10])
    materializer = VideoChunkMaterializer(runner=runner)

    output = await materializer.materialize(
        source,
        video_id=uuid4(),
        span=VideoChunkSpan(start_ms=0, end_ms=5_000),
        chunk_root=tmp_path / "cache",
    )

    assert output.name == "000000000_000005000_source.mp4"
    assert output.stat().st_size == 100


@pytest.mark.asyncio
async def test_materializer_reencodes_oversized_preprocessed_chunk_with_lower_bandwidth(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    runner = MaterializingRunner(sizes=[1500, 1400, 80])
    materializer = VideoChunkMaterializer(runner=runner)

    output = await materializer.materialize(
        source,
        video_id=uuid4(),
        span=VideoChunkSpan(start_ms=0, end_ms=30_000),
        chunk_root=tmp_path / "cache",
    )

    assert output.name == "000000000_000030000.mp4"
    assert output.stat().st_size == 80
    assert len(runner.calls) == 3
    retry_args = runner.calls[2]
    assert retry_args[retry_args.index("-vf") + 1] == "scale=-2:360,fps=3"
    assert retry_args[retry_args.index("-crf") + 1] == "32"


@pytest.mark.asyncio
async def test_materializer_rejects_chunk_outside_upload_limits_before_embedding(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    runner = MaterializingRunner(sizes=[10, 10])
    materializer = VideoChunkMaterializer(runner=runner)

    with pytest.raises(VideoChunkTooSmallError, match="smaller than the DashScope minimum"):
        await materializer.materialize(
            source,
            video_id=uuid4(),
            span=VideoChunkSpan(start_ms=0, end_ms=5_000),
            chunk_root=tmp_path / "cache",
        )


@pytest.mark.asyncio
async def test_materializer_rejects_missing_source_before_ffmpeg(tmp_path: Path) -> None:
    runner = MaterializingRunner()
    materializer = VideoChunkMaterializer(runner=runner)

    with pytest.raises(FileNotFoundError):
        await materializer.materialize(
            tmp_path / "missing.mp4",
            video_id=uuid4(),
            span=VideoChunkSpan(start_ms=0, end_ms=10_000),
            chunk_root=tmp_path / "cache",
        )

    assert runner.calls == []


@pytest.mark.asyncio
async def test_materializer_normalizes_ffmpeg_failure(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    runner = MaterializingRunner(
        result=CommandResult(returncode=1, stdout="", stderr="decoder failed"),
    )
    materializer = VideoChunkMaterializer(runner=runner)

    with pytest.raises(VideoChunkMaterializationError, match="decoder failed"):
        await materializer.materialize(
            source,
            video_id=uuid4(),
            span=VideoChunkSpan(start_ms=0, end_ms=30_000),
            chunk_root=tmp_path / "cache",
        )

from pathlib import Path
from uuid import uuid4

import pytest

from clipatlas.video.chunks import (
    VideoChunkMaterializer,
    VideoChunkSpan,
    VideoChunkTooSmallError,
)
from clipatlas.video.commands import CommandResult


class TinyRunner:
    """所有 ffmpeg 输出都远小于 24KB 下限 → 触发 too-small 分支。"""

    def __init__(self):
        self.calls = []

    async def run(self, args):
        self.calls.append(args)
        Path(args[-1]).write_bytes(b"x" * 8_000)
        return CommandResult(returncode=0, stdout="", stderr="")


@pytest.mark.asyncio
async def test_too_small_chunk_raises_video_chunk_too_small_error(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"fixture")
    runner = TinyRunner()
    with pytest.raises(VideoChunkTooSmallError) as exc_info:
        await VideoChunkMaterializer(runner=runner).materialize(
            source, video_id=uuid4(), span=VideoChunkSpan(0, 5_000),
            chunk_root=tmp_path / "cache",
        )
    message = str(exc_info.value)
    assert "smaller than the DashScope minimum" in message
    assert "prepared=8000" in message


class MixedRunner:
    """第一个输出（原始 copy）太大，第二个（预处理）太小。"""

    def __init__(self):
        self.calls = []

    async def run(self, args):
        self.calls.append(args)
        Path(args[-1]).write_bytes(b"x" * (100_000 if len(self.calls) == 1 else 20_000))
        return CommandResult(returncode=0, stdout="", stderr="")


@pytest.mark.asyncio
async def test_prepared_too_small_but_raw_valid_uses_raw(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"fixture")
    runner = MixedRunner()
    output = await VideoChunkMaterializer(runner=runner).materialize(
        source, video_id=uuid4(), span=VideoChunkSpan(0, 5_000),
        chunk_root=tmp_path / "cache",
    )
    assert output.stat().st_size == 100_000
    assert output.name.endswith("_source.mp4")

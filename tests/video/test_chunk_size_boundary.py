from pathlib import Path
from uuid import uuid4

import pytest

from clipatlas.video.chunks import VideoChunkMaterializer, VideoChunkSpan
from clipatlas.video.commands import CommandResult


@pytest.mark.parametrize(("size", "allowed"), [
    (23_999, False), (24_000, False), (24_181, False), (24_575, False),
    (24_576, True), (24_577, True), (50_700_000, True), (50_700_001, False),
])
def test_real_upload_boundaries_use_24_kib_minimum(size, allowed):
    assert VideoChunkMaterializer._within_upload_limits(size) is allowed


class BoundaryRunner:
    def __init__(self):
        self.calls = []

    async def run(self, args):
        self.calls.append(args)
        Path(args[-1]).write_bytes(b"x" * (65_536 if len(self.calls) == 1 else 24_181))
        return CommandResult(returncode=0, stdout="", stderr="")


@pytest.mark.asyncio
async def test_24181_byte_tail_uses_existing_valid_source_chunk_fallback(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"original source fixture")
    runner = BoundaryRunner()
    output = await VideoChunkMaterializer(runner=runner).materialize(
        source, video_id=uuid4(), span=VideoChunkSpan(60_000, 63_616),
        chunk_root=tmp_path / "cache",
    )
    assert len(runner.calls) == 2
    assert output.name == "000060000_000063616_source.mp4"
    assert output.stat().st_size == 65_536
    assert not output.with_name("000060000_000063616.mp4").exists()
    assert source.read_bytes() == b"original source fixture"

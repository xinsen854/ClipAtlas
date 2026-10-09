from uuid import uuid4

import pytest

from clipatlas.video.storage import LocalVideoStore


async def _chunks(*parts: bytes):
    for part in parts:
        yield part


@pytest.mark.asyncio
async def test_local_store_writes_under_clipatlas_video_id_and_sanitizes_name(tmp_path) -> None:
    video_id = uuid4()
    store = LocalVideoStore(root=tmp_path)

    result = await store.save(
        video_id=video_id,
        source_name="../../unsafe/source.MP4",
        chunks=_chunks(b"abc", b"def"),
    )

    assert result.video_id == video_id
    assert result.source_name == "../../unsafe/source.MP4"
    assert result.path == tmp_path / str(video_id) / "source.mp4"
    assert result.path.read_bytes() == b"abcdef"
    assert result.path.resolve().is_relative_to(tmp_path.resolve())


@pytest.mark.asyncio
async def test_local_store_uses_bin_for_unsafe_extension(tmp_path) -> None:
    video_id = uuid4()
    store = LocalVideoStore(root=tmp_path)

    result = await store.save(
        video_id=video_id,
        source_name="clip.bad$ext",
        chunks=_chunks(b"payload"),
    )

    assert result.path.name == "source.bin"
    assert result.path.read_bytes() == b"payload"

import asyncio
from pathlib import Path
from uuid import UUID

import pytest

from clipatlas.domain.models import VideoAsset
from clipatlas.ocr.indexer import OCRIndexer
from clipatlas.ocr.models import OCRFrame, OCRSampleStatus
from clipatlas.ocr.store import OCRStore
from clipatlas.providers.errors import ProviderRequestError


class FakeMaterializer:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls: list[int] = []

    async def materialize(
        self,
        *,
        source: Path,
        video_id: UUID,
        timestamp_ms: int,
    ) -> OCRFrame:
        self.calls.append(timestamp_ms)
        path = self.root / str(video_id) / f"{timestamp_ms:012d}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(b"jpeg")
        return OCRFrame(timestamp_ms=timestamp_ms, path=path)


class FakeOCRProvider:
    name = "bailian-ocr"
    model = "qwen3.5-ocr"

    def __init__(self, *, fail_on_call: int | None = None) -> None:
        self.calls = 0
        self.fail_on_call = fail_on_call

    async def recognize(self, image_path: Path) -> str:
        self.calls += 1
        if self.calls == self.fail_on_call:
            raise ProviderRequestError("transient OCR failure")
        return f"text-{self.calls}"


@pytest.mark.asyncio
async def test_ocr_indexer_resumes_failed_sample_and_deletes_only_successful_frames(
    tmp_path: Path,
) -> None:
    source = tmp_path / "video.mp4"
    source.write_bytes(b"video")
    video = VideoAsset(filename="video.mp4", source_uri=str(source), duration_ms=12_000)
    store = OCRStore(tmp_path / "library.sqlite3")
    materializer = FakeMaterializer(tmp_path / "frames")
    provider = FakeOCRProvider(fail_on_call=2)
    indexer = OCRIndexer(
        store=store,
        provider=provider,
        materializer=materializer,
        interval_ms=5_000,
    )

    with pytest.raises(ProviderRequestError, match="transient"):
        await indexer.index_video(video, source)

    first = store.get_sample(
        video.id,
        0,
        5_000,
        5_000,
        provider.name,
        provider.model,
        revision=1,
    )
    second = store.get_sample(
        video.id,
        5_000,
        10_000,
        5_000,
        provider.name,
        provider.model,
        revision=1,
    )
    assert first is not None and first.status is OCRSampleStatus.COMPLETED
    assert first.text == "text-1"
    assert second is not None and second.status is OCRSampleStatus.FAILED
    assert second.attempt_count == 1
    assert not (tmp_path / "frames" / str(video.id) / "000000000000.jpg").exists()
    assert (tmp_path / "frames" / str(video.id) / "000000005000.jpg").exists()

    retry_provider = FakeOCRProvider()
    retry = OCRIndexer(
        store=store,
        provider=retry_provider,
        materializer=materializer,
        interval_ms=5_000,
    )
    processed = await retry.index_video(video, source)

    assert processed == 2
    assert retry_provider.calls == 2
    second = store.get_sample(
        video.id,
        5_000,
        10_000,
        5_000,
        retry_provider.name,
        retry_provider.model,
        revision=1,
    )
    final = store.get_sample(
        video.id,
        10_000,
        12_000,
        5_000,
        retry_provider.name,
        retry_provider.model,
        revision=1,
    )
    assert second is not None and second.status is OCRSampleStatus.COMPLETED
    assert second.attempt_count == 2
    assert final is not None and final.status is OCRSampleStatus.COMPLETED
    assert final.end_ms == 12_000
    assert not (tmp_path / "frames" / str(video.id) / "000000005000.jpg").exists()
    assert not (tmp_path / "frames" / str(video.id) / "000000010000.jpg").exists()


@pytest.mark.asyncio
async def test_ocr_force_reparse_creates_new_revision_without_overwriting_history(
    tmp_path: Path,
) -> None:
    source = tmp_path / "video.mp4"
    source.write_bytes(b"video")
    video = VideoAsset(filename="video.mp4", source_uri=str(source), duration_ms=1_000)
    store = OCRStore(tmp_path / "library.sqlite3")
    materializer = FakeMaterializer(tmp_path / "frames")
    provider = FakeOCRProvider()
    indexer = OCRIndexer(
        store=store,
        provider=provider,
        materializer=materializer,
        interval_ms=5_000,
    )

    await indexer.index_video(video, source)
    await indexer.index_video(video, source)
    assert provider.calls == 1

    await indexer.index_video(video, source, force=True)
    assert provider.calls == 2
    assert store.get_latest_revision(
        video.id,
        provider.name,
        provider.model,
        interval_ms=5_000,
    ) == 2
    history = store.list_samples(video.id, provider.name, provider.model)
    assert [record.revision for record in history] == [1, 2]


@pytest.mark.asyncio
async def test_parallel_ocr_bounded_inputs_single_revision_and_resume(tmp_path):
    source = tmp_path / "video.mp4"
    source.write_bytes(b"fixture")
    video = VideoAsset(filename="video.mp4", source_uri=str(source), duration_ms=5000 * 6)
    store = OCRStore(tmp_path / "library.sqlite3")
    ready, release = asyncio.Event(), asyncio.Event()

    class Provider(FakeOCRProvider):
        active = 0
        peak = 0

        async def recognize(self, path):
            self.calls += 1
            self.active += 1
            self.peak = max(self.peak, self.active)
            if self.active == 3:
                ready.set()
            await release.wait()
            assert path.exists()  # input stays alive until the upload finishes
            await asyncio.sleep(0)
            self.active -= 1
            return "<p>recognized</p>"

    provider = Provider()
    indexer = OCRIndexer(store=store, provider=provider, materializer=FakeMaterializer(tmp_path),
                       concurrency=3, interval_ms=5000)
    task = asyncio.create_task(indexer.index_video(video, source))
    await asyncio.wait_for(ready.wait(), timeout=2)
    await asyncio.sleep(0)
    assert len(list(tmp_path.rglob("*.jpg"))) == 4
    release.set()
    assert await task == 6
    assert provider.peak == 3
    assert await indexer.index_video(video, source) == 0
    assert provider.calls == 6
    assert store.get_latest_revision(video.id, provider.name, provider.model, interval_ms=5000) == 1
    assert await indexer.index_video(video, source, force=True) == 6
    assert store.get_latest_revision(video.id, provider.name, provider.model, interval_ms=5000) == 2

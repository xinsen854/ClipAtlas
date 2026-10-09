import asyncio
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest

from clipatlas.asr.audio import ASRAudioChunkMaterializer, MAX_ASR_CHUNK_DURATION_MS
from clipatlas.asr.indexer import ASRIndexer
from clipatlas.asr.models import ASRAudioChunk, ASRChunkStatus, ASRSentence
from clipatlas.asr.qwen import QwenAudioASRProvider
from clipatlas.asr.store import ASRStore
from clipatlas.domain.models import VideoAsset
from clipatlas.providers.errors import (
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderRequestError,
)
from clipatlas.video.commands import CommandResult


class RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def run(self, args: list[str]) -> CommandResult:
        self.calls.append(args)
        destination = Path(args[-1])
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"RIFF" + b"0" * 128)
        return CommandResult(returncode=0, stdout="", stderr="")


def _sentence_event(
    *,
    start_ms: int,
    end_ms: int,
    text: str,
    final: bool = True,
    words: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "output": {
            "sentence": {
                "begin_time": start_ms,
                "end_time": end_ms,
                "sentence_end": final,
                "text": text,
                "words": words or [],
            }
        }
    }


@pytest.mark.asyncio
async def test_audio_materializer_extracts_and_reuses_bounded_mono_16k_wav(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    runner = RecordingRunner()
    materializer = ASRAudioChunkMaterializer(tmp_path / "asr", runner=runner)
    video_id = uuid4()

    chunk = await materializer.materialize(
        source=source,
        video_id=video_id,
        start_ms=45_000,
        end_ms=MAX_ASR_CHUNK_DURATION_MS,
    )

    assert chunk.path.name == f"{45_000:012d}-{MAX_ASR_CHUNK_DURATION_MS:012d}.wav"
    assert runner.calls == [
        [
            "ffmpeg",
            "-y",
            "-ss",
            "45.000",
            "-i",
            str(source.resolve()),
            "-t",
            f"{(MAX_ASR_CHUNK_DURATION_MS - 45_000) / 1000:.3f}",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(chunk.path),
        ]
    ]

    assert await materializer.materialize(
        source=source,
        video_id=video_id,
        start_ms=45_000,
        end_ms=MAX_ASR_CHUNK_DURATION_MS,
    ) == chunk
    assert len(runner.calls) == 1


@pytest.mark.asyncio
async def test_qwen_asr_uses_bailian_sse_contract_and_keeps_only_final_sentences(
    tmp_path: Path,
) -> None:
    audio = tmp_path / "chunk.wav"
    audio.write_bytes(b"RIFFaudio")
    captured: dict[str, Any] = {}
    final_words = [
        {"begin_time": 100, "end_time": 300, "text": "开始", "punctuation": ""},
        {"begin_time": 300, "end_time": 900, "text": "越野测试", "punctuation": "。"},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["json"] = json.loads(request.content)
        events = [
            _sentence_event(start_ms=0, end_ms=400, text="越野", final=False),
            _sentence_event(
                start_ms=100,
                end_ms=900,
                text="开始越野测试。",
                words=final_words,
            ),
            _sentence_event(start_ms=1100, end_ms=1700, text="路面很颠簸。"),
        ]
        body = "\n\n".join(
            f"data: {json.dumps(event, ensure_ascii=False)}" for event in events
        ) + "\n\n"
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = QwenAudioASRProvider(
            api_key="secret-key",
            api_root="https://workspace.cn-beijing.maas.aliyuncs.com/api/v1/",
            client=client,
        )
        sentences = await provider.transcribe(audio)

    assert [(item.start_ms, item.end_ms, item.text) for item in sentences] == [
        (100, 900, "开始越野测试。"),
        (1100, 1700, "路面很颠簸。"),
    ]
    assert sentences[0].words[1].text == "越野测试"
    assert sentences[0].words[1].punctuation == "。"
    assert captured["url"].endswith("/services/aigc/multimodal-generation/generation")
    assert captured["headers"]["authorization"] == "Bearer secret-key"
    assert captured["headers"]["x-dashscope-sse"] == "enable"
    payload = captured["json"]
    assert payload["model"] == "qwen-audio-3.0-asr-flash"
    assert payload["parameters"] == {"format": "wav", "sample_rate": 16000}
    data = payload["input"]["messages"][0]["content"][0]["input_audio"]["data"]
    assert data.startswith("data:audio/wav;base64,")


@pytest.mark.asyncio
async def test_qwen_asr_accepts_short_non_streaming_json_response(tmp_path: Path) -> None:
    audio = tmp_path / "short.wav"
    audio.write_bytes(b"RIFFshort")
    event = _sentence_event(start_ms=80, end_ms=2500, text="短视频也要有时间戳。")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=event, headers={"content-type": "application/json"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = QwenAudioASRProvider(
            api_key="key",
            api_root="https://workspace.cn-beijing.maas.aliyuncs.com/api/v1",
            client=client,
        )
        sentences = await provider.transcribe(audio)

    assert [(item.start_ms, item.end_ms, item.text) for item in sentences] == [
        (80, 2500, "短视频也要有时间戳。")
    ]


@pytest.mark.asyncio
async def test_qwen_asr_rejects_base64_over_10mb_before_network(tmp_path: Path) -> None:
    audio = tmp_path / "too-large.wav"
    audio.write_bytes(b"0" * 7_500_000)
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = QwenAudioASRProvider(
            api_key="key",
            api_root="https://x.aliyuncs.com/api/v1",
            client=client,
        )
        with pytest.raises(ProviderRequestError, match="10 MB"):
            await provider.transcribe(audio)

    assert called is False


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (401, ProviderAuthenticationError),
        (403, ProviderAuthenticationError),
        (429, ProviderRateLimitError),
        (500, ProviderRequestError),
    ],
)
@pytest.mark.asyncio
async def test_qwen_asr_normalizes_http_errors(
    tmp_path: Path,
    status: int,
    error_type: type[Exception],
) -> None:
    audio = tmp_path / "chunk.wav"
    audio.write_bytes(b"RIFF")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"message": "upstream failed"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = QwenAudioASRProvider(
            api_key="key",
            api_root="https://x.aliyuncs.com/api/v1",
            client=client,
        )
        with pytest.raises(error_type):
            await provider.transcribe(audio)


class FakeMaterializer:
    def __init__(self, root: Path) -> None:
        self.root = root

    async def materialize(
        self,
        *,
        source: Path,
        video_id: Any,
        start_ms: int,
        end_ms: int,
    ) -> ASRAudioChunk:
        path = self.root / f"{start_ms}-{end_ms}.wav"
        path.write_bytes(b"RIFF")
        return ASRAudioChunk(start_ms=start_ms, end_ms=end_ms, path=path)


class FakeASRProvider:
    name = "bailian-asr"
    model = "qwen-audio-3.0-asr-flash"

    def __init__(self, *, fail_on_call: int | None = None) -> None:
        self.calls = 0
        self.fail_on_call = fail_on_call

    async def transcribe(self, audio_path: Path) -> list[ASRSentence]:
        self.calls += 1
        if self.fail_on_call == self.calls:
            raise ProviderRequestError("transient upstream failure")
        return [
            ASRSentence(
                start_ms=100,
                end_ms=600,
                text=f"sentence-{self.calls}",
            )
        ]


@pytest.mark.asyncio
async def test_asr_indexer_resumes_failed_chunk_and_shifts_absolute_timestamps(
    tmp_path: Path,
) -> None:
    store = ASRStore(tmp_path / "catalog.sqlite3")
    source = tmp_path / "video.mp4"
    source.write_bytes(b"video")
    chunk_ms = MAX_ASR_CHUNK_DURATION_MS
    video = VideoAsset(
        filename="video.mp4",
        source_uri=str(source),
        duration_ms=chunk_ms * 2 + 40_000,
    )
    provider = FakeASRProvider(fail_on_call=2)
    indexer = ASRIndexer(
        store=store,
        provider=provider,
        materializer=FakeMaterializer(tmp_path),
    )

    with pytest.raises(ProviderRequestError, match="transient"):
        await indexer.index_video(video, source)

    first = store.get_asr_chunk(
        video.id, 0, chunk_ms, provider.name, provider.model, revision=1
    )
    failed = store.get_asr_chunk(
        video.id, chunk_ms, chunk_ms * 2, provider.name, provider.model, revision=1
    )
    assert first is not None and first.status is ASRChunkStatus.COMPLETED
    assert not (tmp_path / f"0-{chunk_ms}.wav").exists()
    assert failed is not None and failed.status is ASRChunkStatus.FAILED
    assert failed.attempt_count == 1
    assert (tmp_path / f"{chunk_ms}-{chunk_ms * 2}.wav").exists()

    retry_provider = FakeASRProvider()
    await ASRIndexer(
        store=store,
        provider=retry_provider,
        materializer=FakeMaterializer(tmp_path),
    ).index_video(video, source)

    assert retry_provider.calls == 2
    retried = store.get_asr_chunk(
        video.id,
        chunk_ms,
        chunk_ms * 2,
        retry_provider.name,
        retry_provider.model,
        revision=1,
    )
    tail = store.get_asr_chunk(
        video.id,
        chunk_ms * 2,
        video.duration_ms,
        retry_provider.name,
        retry_provider.model,
        revision=1,
    )
    assert retried is not None and retried.status is ASRChunkStatus.COMPLETED
    assert retried.attempt_count == 2
    assert retried.sentences[0].start_ms == chunk_ms + 100
    assert retried.sentences[0].end_ms == chunk_ms + 600
    assert tail is not None and tail.end_ms == video.duration_ms
    assert not (tmp_path / f"{chunk_ms}-{chunk_ms * 2}.wav").exists()


@pytest.mark.asyncio
async def test_asr_force_reparse_creates_revision_without_overwriting_history(
    tmp_path: Path,
) -> None:
    store = ASRStore(tmp_path / "catalog.sqlite3")
    source = tmp_path / "video.mp4"
    source.write_bytes(b"video")
    video = VideoAsset(filename="video.mp4", source_uri=str(source), duration_ms=1000)
    provider = FakeASRProvider()
    indexer = ASRIndexer(
        store=store,
        provider=provider,
        materializer=FakeMaterializer(tmp_path),
    )

    await indexer.index_video(video, source)
    await indexer.index_video(video, source)
    assert provider.calls == 1

    await indexer.index_video(video, source, force=True)
    assert provider.calls == 2
    assert store.get_latest_asr_revision(video.id, provider.name, provider.model) == 2
    assert [
        record.revision for record in store.list_asr_chunks(video.id, provider.name, provider.model)
    ] == [1, 2]


@pytest.mark.asyncio
async def test_parallel_asr_bounded_inputs_single_revision_and_resume(tmp_path):
    source = tmp_path / "video.mp4"
    source.write_bytes(b"fixture")
    video = VideoAsset(filename="video.mp4", source_uri=str(source), duration_ms=MAX_ASR_CHUNK_DURATION_MS * 6)
    store = ASRStore(tmp_path / "library.sqlite3")
    ready, release = asyncio.Event(), asyncio.Event()

    class Provider(FakeASRProvider):
        active = 0
        peak = 0

        async def transcribe(self, path):
            self.calls += 1
            self.active += 1
            self.peak = max(self.peak, self.active)
            if self.active == 3:
                ready.set()
            await release.wait()
            assert path.exists()  # input stays alive until the upload finishes
            await asyncio.sleep(0)
            self.active -= 1
            return [ASRSentence(start_ms=100, end_ms=600, text="recognized")]

    provider = Provider()
    indexer = ASRIndexer(store=store, provider=provider, materializer=FakeMaterializer(tmp_path),
                       concurrency=3)
    task = asyncio.create_task(indexer.index_video(video, source))
    await asyncio.wait_for(ready.wait(), timeout=2)
    await asyncio.sleep(0)
    assert len(list(tmp_path.rglob("*.wav"))) == 4
    release.set()
    assert await task == 6
    assert provider.peak == 3
    assert await indexer.index_video(video, source) == 0
    assert provider.calls == 6
    assert store.get_latest_asr_revision(video.id, provider.name, provider.model) == 1
    assert await indexer.index_video(video, source, force=True) == 6
    assert store.get_latest_asr_revision(video.id, provider.name, provider.model) == 2

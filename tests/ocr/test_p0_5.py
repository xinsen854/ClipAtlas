import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from clipatlas.ocr.frames import OCRFrameMaterializer
from clipatlas.ocr.models import OCRSampleRecord, OCRSampleStatus, OCRSpan
from clipatlas.ocr.qwen import QwenOCRProvider
from clipatlas.ocr.store import OCRStore
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
        destination.write_bytes(b"jpeg")
        return CommandResult(returncode=0, stdout="", stderr="")


def _sample(
    video_id: UUID,
    *,
    start_ms: int,
    end_ms: int,
    text: str,
) -> OCRSampleRecord:
    return OCRSampleRecord(
        video_id=video_id,
        start_ms=start_ms,
        end_ms=end_ms,
        interval_ms=5_000,
        provider="bailian-ocr",
        model="qwen3.5-ocr",
        revision=1,
        status=OCRSampleStatus.COMPLETED,
        attempt_count=1,
        text=text,
    )


def test_ocr_store_merges_consecutive_equivalent_text_into_one_span(tmp_path) -> None:
    store = OCRStore(tmp_path / "library.sqlite3")
    video_id = uuid4()
    store.save_sample(_sample(video_id, start_ms=0, end_ms=5_000, text="越野测试\n"))
    store.save_sample(
        _sample(video_id, start_ms=5_000, end_ms=10_000, text="  越野测试  ")
    )

    assert store.list_spans(
        video_id,
        "bailian-ocr",
        "qwen3.5-ocr",
        revision=1,
        interval_ms=5_000,
    ) == [OCRSpan(start_ms=0, end_ms=10_000, text="越野测试")]

    samples = store.list_samples(video_id, "bailian-ocr", "qwen3.5-ocr")
    assert [sample.text for sample in samples] == ["越野测试\n", "  越野测试  "]


def test_ocr_blank_sample_breaks_text_span_continuity(tmp_path) -> None:
    store = OCRStore(tmp_path / "library.sqlite3")
    video_id = uuid4()
    store.save_sample(_sample(video_id, start_ms=0, end_ms=5_000, text="越野测试"))
    store.save_sample(_sample(video_id, start_ms=5_000, end_ms=10_000, text=" \n "))
    store.save_sample(_sample(video_id, start_ms=10_000, end_ms=15_000, text="越野测试"))

    assert store.list_spans(
        video_id,
        "bailian-ocr",
        "qwen3.5-ocr",
        revision=1,
        interval_ms=5_000,
    ) == [
        OCRSpan(start_ms=0, end_ms=5_000, text="越野测试"),
        OCRSpan(start_ms=10_000, end_ms=15_000, text="越野测试"),
    ]


@pytest.mark.asyncio
async def test_ocr_frame_materializer_extracts_and_reuses_deterministic_frame(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    runner = RecordingRunner()
    video_id = uuid4()
    materializer = OCRFrameMaterializer(tmp_path / "ocr", runner=runner)

    frame = await materializer.materialize(
        source=source,
        video_id=video_id,
        timestamp_ms=5_000,
    )

    assert frame.timestamp_ms == 5_000
    assert frame.path.name == "000000005000.jpg"
    assert runner.calls == [
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-ss",
            "5.000",
            "-i",
            str(source.resolve()),
            "-frames:v",
            "1",
            "-q:v",
            "3",
            str(frame.path),
        ]
    ]

    reused = await materializer.materialize(
        source=source,
        video_id=video_id,
        timestamp_ms=5_000,
    )
    assert reused == frame
    assert len(runner.calls) == 1


@pytest.mark.asyncio
async def test_qwen_ocr_uses_bailian_openai_http_and_returns_raw_text(tmp_path: Path) -> None:
    image = tmp_path / "frame.jpg"
    image.write_bytes(b"jpeg")
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["json"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "越野测试\n"}}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = QwenOCRProvider(
            api_key="secret-key",
            base_url="https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/",
            client=client,
        )
        text = await provider.recognize(image)

    assert provider.name == "bailian-ocr"
    assert provider.model == "qwen3.5-ocr"
    assert text == "越野测试\n"
    assert captured["url"] == (
        "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions"
    )
    assert captured["headers"]["authorization"] == "Bearer secret-key"
    payload = captured["json"]
    assert payload["model"] == "qwen3.5-ocr"
    content = payload["messages"][0]["content"]
    assert content[0]["type"] == "image_url"
    assert content[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert content[0]["min_pixels"] == 3072
    assert content[0]["max_pixels"] == 8388608
    assert content[1] == {
        "type": "text",
        "text": (
            "You are an OCR engine, not an image-captioning model. Extract only text that is "
            "visibly printed, overlaid, subtitled, or written in the image. Preserve the visible "
            "text's original language and spelling exactly. Do not translate, summarize, infer, "
            "explain, or describe people, objects, actions, scenes, atmosphere, or story. If the "
            "image contains no visible text, return an empty string. Output raw OCR text only, "
            "without Markdown, JSON, labels, or commentary."
        ),
    }


@pytest.mark.asyncio
async def test_qwen_ocr_rejects_base64_data_uri_over_10mb_before_network(
    tmp_path: Path,
) -> None:
    image = tmp_path / "too-large.jpg"
    image.write_bytes(b"0" * 7_500_000)
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = QwenOCRProvider(
            api_key="key",
            base_url="https://x.aliyuncs.com/compatible-mode/v1",
            client=client,
        )
        with pytest.raises(ProviderRequestError, match="10 MB"):
            await provider.recognize(image)

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
async def test_qwen_ocr_normalizes_http_errors(
    tmp_path: Path,
    status: int,
    error_type: type[Exception],
) -> None:
    image = tmp_path / "frame.jpg"
    image.write_bytes(b"jpeg")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"message": "upstream failed"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = QwenOCRProvider(
            api_key="key",
            base_url="https://x.aliyuncs.com/compatible-mode/v1",
            client=client,
        )
        with pytest.raises(error_type):
            await provider.recognize(image)


@pytest.mark.asyncio
async def test_qwen_ocr_rejects_malformed_success_payload(tmp_path: Path) -> None:
    image = tmp_path / "frame.jpg"
    image.write_bytes(b"jpeg")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = QwenOCRProvider(
            api_key="key",
            base_url="https://x.aliyuncs.com/compatible-mode/v1",
            client=client,
        )
        with pytest.raises(ProviderRequestError, match="invalid"):
            await provider.recognize(image)

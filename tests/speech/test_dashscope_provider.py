import json

import httpx
import pytest

from clipatlas.speech.dashscope import DashScopeSpeechProvider
from clipatlas.speech.errors import (
    SpeechAuthenticationError,
    SpeechConfigurationError,
    SpeechRateLimitError,
    SpeechRequestError,
)
from clipatlas.speech.models import SpeechSynthesisRequest


@pytest.mark.asyncio
async def test_dashscope_posts_official_http_payload_and_downloads_audio() -> None:
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "POST":
            payload = json.loads(request.content)
            assert request.url == httpx.URL(
                "https://workspace.example.com/api/v1/services/audio/tts/SpeechSynthesizer"
            )
            assert request.headers["Authorization"] == "Bearer secret"
            assert payload == {
                "model": "cosyvoice-v3.5-flash",
                "input": {
                    "text": "测试旁白",
                    "voice": "custom-voice-1",
                    "format": "wav",
                    "sample_rate": 48000,
                    "volume": 60,
                    "rate": 1.1,
                    "pitch": 0.95,
                    "language_hints": ["zh"],
                    "instruction": "克制、平静地讲述",
                },
            }
            return httpx.Response(
                200,
                json={
                    "request_id": "req-1",
                    "output": {
                        "finish_reason": "stop",
                        "audio": {
                            "data": "",
                            "url": "https://audio.example.com/result.wav",
                            "id": "audio-1",
                            "expires_at": 1_800_000_000,
                        },
                    },
                    "usage": {"characters": 4},
                },
            )
        assert request.url == httpx.URL("https://audio.example.com/result.wav")
        return httpx.Response(200, content=b"RIFF\x00\x00\x00\x00WAVE")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = DashScopeSpeechProvider(
            api_key="secret",
            base_url="https://workspace.example.com/api/v1/services/audio/tts/SpeechSynthesizer",
            client=client,
        )
        result = await provider.synthesize(
            SpeechSynthesisRequest(
                text="测试旁白",
                voice_id="custom-voice-1",
                language="zh-CN",
                speed=1.1,
                pitch=0.95,
                volume=1.2,
                emotion="sad",
                instruction="克制、平静地讲述",
                output_format="wav",
                sample_rate=48000,
            )
        )

    assert len(calls) == 2
    assert result.provider == "dashscope"
    assert result.model == "cosyvoice-v3.5-flash"
    assert result.audio_bytes == b"RIFF\x00\x00\x00\x00WAVE"
    assert result.output_format == "wav"
    assert result.sample_rate == 48000
    assert result.duration_ms is None
    assert result.word_timings == []
    assert result.raw_payload["request_id"] == "req-1"


@pytest.mark.asyncio
async def test_dashscope_capabilities_match_non_streaming_http_adapter() -> None:
    provider = DashScopeSpeechProvider(api_key="secret")

    voices = await provider.list_voices()

    assert voices == []
    assert provider.name == "dashscope"
    assert provider.capabilities.preset_voices is False
    assert provider.capabilities.speed_control is True
    assert provider.capabilities.pitch_control is True
    assert provider.capabilities.volume_control is True
    assert provider.capabilities.emotion_control is False
    assert provider.capabilities.instruction_control is True
    assert provider.capabilities.voice_clone is True
    assert provider.capabilities.voice_design is True
    assert provider.capabilities.word_timestamps is False
    assert provider.capabilities.streaming is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [
        (401, SpeechAuthenticationError),
        (403, SpeechAuthenticationError),
        (429, SpeechRateLimitError),
        (500, SpeechRequestError),
    ],
)
async def test_dashscope_normalizes_http_errors(
    status_code: int,
    error_type: type[Exception],
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"message": "vendor error"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = DashScopeSpeechProvider(api_key="secret", client=client)
        with pytest.raises(error_type):
            await provider.synthesize(
                SpeechSynthesisRequest(text="测试", voice_id="custom-voice-1")
            )


@pytest.mark.asyncio
async def test_dashscope_normalizes_network_failure() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network down", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = DashScopeSpeechProvider(api_key="secret", client=client)
        with pytest.raises(SpeechRequestError, match="network down"):
            await provider.synthesize(
                SpeechSynthesisRequest(text="测试", voice_id="custom-voice-1")
            )


@pytest.mark.asyncio
async def test_dashscope_rejects_malformed_or_empty_audio_response() -> None:
    responses = [
        httpx.Response(200, json={"request_id": "req-1", "output": {}}),
        httpx.Response(
            200,
            json={
                "request_id": "req-2",
                "output": {"audio": {"url": "file:///tmp/unsafe.wav"}},
            },
        ),
    ]

    for response in responses:

        async def handler(
            request: httpx.Request,
            response: httpx.Response = response,
        ) -> httpx.Response:
            return response

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = DashScopeSpeechProvider(api_key="secret", client=client)
            with pytest.raises(SpeechRequestError):
                await provider.synthesize(
                    SpeechSynthesisRequest(text="测试", voice_id="custom-voice-1")
                )

    async def empty_audio_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "request_id": "req-3",
                    "output": {"audio": {"url": "https://audio.example.com/empty.wav"}},
                },
            )
        return httpx.Response(200, content=b"")

    async with httpx.AsyncClient(transport=httpx.MockTransport(empty_audio_handler)) as client:
        provider = DashScopeSpeechProvider(api_key="secret", client=client)
        with pytest.raises(SpeechRequestError, match="empty audio"):
            await provider.synthesize(
                SpeechSynthesisRequest(text="测试", voice_id="custom-voice-1")
            )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("synthesis_request", "message"),
    [
        (SpeechSynthesisRequest(text="测试", voice_id="v", speed=0.4), "speed"),
        (SpeechSynthesisRequest(text="测试", voice_id="v", pitch=2.1), "pitch"),
        (SpeechSynthesisRequest(text="测试", voice_id="v", volume=2.1), "volume"),
        (SpeechSynthesisRequest(text="测试", voice_id="v", sample_rate=12345), "sample rate"),
        (SpeechSynthesisRequest(text="测试", voice_id="v", language="xx-YY"), "language"),
    ],
)
async def test_dashscope_validates_provider_specific_ranges(
    synthesis_request: SpeechSynthesisRequest,
    message: str,
) -> None:
    provider = DashScopeSpeechProvider(api_key="secret")

    with pytest.raises(SpeechConfigurationError, match=message):
        await provider.synthesize(synthesis_request)

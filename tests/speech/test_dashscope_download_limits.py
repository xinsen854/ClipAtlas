import httpx
import pytest

from clipatlas.speech.dashscope import DashScopeSpeechProvider
from clipatlas.speech.errors import SpeechRequestError
from clipatlas.speech.models import SpeechSynthesisRequest


@pytest.mark.asyncio
async def test_dashscope_audio_download_is_bounded() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "request_id": "req-1",
                    "output": {
                        "audio": {"url": "https://audio.example.com/result.wav"}
                    },
                },
            )
        return httpx.Response(200, content=b"123456789")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = DashScopeSpeechProvider(
            api_key="secret",
            client=client,
            max_audio_bytes=8,
        )
        with pytest.raises(SpeechRequestError, match="maximum audio size"):
            await provider.synthesize(
                SpeechSynthesisRequest(text="测试", voice_id="custom-voice-1")
            )

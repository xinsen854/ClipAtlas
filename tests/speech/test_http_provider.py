import base64
import json

import httpx
import pytest

from clipatlas.speech.contracts import SpeechProviderCapabilities
from clipatlas.speech.errors import (
    SpeechAuthenticationError,
    SpeechConfigurationError,
    SpeechRateLimitError,
    SpeechRequestError,
)
from clipatlas.speech.http_provider import (
    GenericHttpSpeechProvider,
    HttpSpeechProviderConfig,
    HttpSpeechResponseMode,
    LocalHttpSpeechProvider,
)
from clipatlas.speech.models import SpeechSynthesisRequest


@pytest.mark.asyncio
async def test_generic_provider_sends_only_declared_fields_headers_and_timeout() -> None:
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        payload = json.loads(request.content)
        assert payload == {
            "prompt": "测试旁白",
            "speaker": "voice-1",
            "speed": 1.1,
        }
        assert request.headers["X-API-Key"] == "secret"
        timeout = request.extensions["timeout"]
        assert timeout["connect"] == 3.0
        assert timeout["read"] == 3.0
        return httpx.Response(200, content=b"audio-bytes")

    config = HttpSpeechProviderConfig(
        name="custom",
        model="custom-v1",
        endpoint="https://tts.example.com/v1/synthesize",
        method="POST",
        headers={"X-API-Key": "secret"},
        field_mappings={
            "text": "prompt",
            "voice_id": "speaker",
            "speed": "speed",
        },
        response_mode=HttpSpeechResponseMode.BYTES,
        timeout_seconds=3.0,
        max_response_bytes=1024,
        output_format="wav",
        sample_rate=48000,
        capabilities=SpeechProviderCapabilities(speed_control=True),
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = GenericHttpSpeechProvider(config=config, client=client)
        result = await provider.synthesize(
            SpeechSynthesisRequest(
                text="测试旁白",
                voice_id="voice-1",
                speed=1.1,
                pitch=1.2,
                emotion="sad",
            )
        )

    assert len(seen) == 1
    assert result.provider == "custom"
    assert result.model == "custom-v1"
    assert result.audio_bytes == b"audio-bytes"
    assert result.output_format == "wav"
    assert result.sample_rate == 48000
    assert "secret" not in json.dumps(result.raw_payload)


@pytest.mark.asyncio
async def test_base64_response_mode_decodes_declared_json_field() -> None:
    encoded = base64.b64encode(b"decoded-audio").decode("ascii")

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"audio": encoded}})

    config = HttpSpeechProviderConfig(
        name="custom",
        model="v1",
        endpoint="https://tts.example.com/synth",
        field_mappings={"text": "text"},
        response_mode=HttpSpeechResponseMode.BASE64,
        response_field="data.audio",
        max_response_bytes=1024,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await GenericHttpSpeechProvider(config=config, client=client).synthesize(
            SpeechSynthesisRequest(text="hello", voice_id="voice")
        )

    assert result.audio_bytes == b"decoded-audio"


@pytest.mark.asyncio
async def test_url_response_mode_fetches_audio_without_forwarding_secret_headers() -> None:
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "POST":
            return httpx.Response(
                200,
                json={"result": {"audio_url": "https://cdn.example.com/audio.wav"}},
            )
        assert request.url == httpx.URL("https://cdn.example.com/audio.wav")
        assert "X-API-Key" not in request.headers
        return httpx.Response(200, content=b"remote-audio")

    config = HttpSpeechProviderConfig(
        name="custom",
        model="v1",
        endpoint="https://tts.example.com/synth",
        headers={"X-API-Key": "secret"},
        field_mappings={"text": "text"},
        response_mode=HttpSpeechResponseMode.URL,
        response_field="result.audio_url",
        max_response_bytes=1024,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await GenericHttpSpeechProvider(config=config, client=client).synthesize(
            SpeechSynthesisRequest(text="hello", voice_id="voice")
        )

    assert len(calls) == 2
    assert result.audio_bytes == b"remote-audio"


@pytest.mark.asyncio
async def test_response_size_limit_applies_to_direct_and_remote_audio() -> None:
    async def direct_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"123456")

    direct_config = HttpSpeechProviderConfig(
        name="custom",
        model="v1",
        endpoint="https://tts.example.com/synth",
        field_mappings={"text": "text"},
        response_mode=HttpSpeechResponseMode.BYTES,
        max_response_bytes=5,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(direct_handler)) as client:
        with pytest.raises(SpeechRequestError, match="maximum response size"):
            await GenericHttpSpeechProvider(config=direct_config, client=client).synthesize(
                SpeechSynthesisRequest(text="hello", voice_id="voice")
            )

    async def remote_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"audio_url": "https://cdn.example.com/a.wav"})
        return httpx.Response(200, content=b"123456")

    remote_config = HttpSpeechProviderConfig(
        name="custom",
        model="v1",
        endpoint="https://tts.example.com/synth",
        field_mappings={"text": "text"},
        response_mode=HttpSpeechResponseMode.URL,
        response_field="audio_url",
        max_response_bytes=5,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(remote_handler)) as client:
        with pytest.raises(SpeechRequestError, match="maximum response size"):
            await GenericHttpSpeechProvider(config=remote_config, client=client).synthesize(
                SpeechSynthesisRequest(text="hello", voice_id="voice")
            )


@pytest.mark.parametrize(
    "endpoint",
    [
        "ftp://tts.example.com/synth",
        "file:///tmp/tts.sock",
        "javascript:alert(1)",
    ],
)
def test_generic_provider_rejects_unsafe_endpoint_schemes(endpoint: str) -> None:
    with pytest.raises(SpeechConfigurationError, match="http or https"):
        GenericHttpSpeechProvider(
            config=HttpSpeechProviderConfig(
                name="custom",
                model="v1",
                endpoint=endpoint,
                field_mappings={"text": "text"},
            )
        )


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://example.com/synth",
        "http://192.168.1.10:8000/tts",
        "http://10.0.0.2:8000/tts",
    ],
)
def test_local_provider_rejects_non_loopback_endpoints(endpoint: str) -> None:
    with pytest.raises(SpeechConfigurationError, match="loopback"):
        LocalHttpSpeechProvider(
            config=HttpSpeechProviderConfig(
                name="local",
                model="local-v1",
                endpoint=endpoint,
                field_mappings={"text": "text"},
            )
        )


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://localhost:8000/tts",
        "http://127.0.0.1:8000/tts",
        "http://[::1]:8000/tts",
    ],
)
def test_local_provider_accepts_loopback_endpoints(endpoint: str) -> None:
    provider = LocalHttpSpeechProvider(
        config=HttpSpeechProviderConfig(
            name="local",
            model="local-v1",
            endpoint=endpoint,
            field_mappings={"text": "text"},
        )
    )

    assert provider.name == "local"


@pytest.mark.asyncio
async def test_local_url_response_cannot_escape_loopback() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"audio_url": "https://cdn.example.com/audio.wav"})

    config = HttpSpeechProviderConfig(
        name="local",
        model="local-v1",
        endpoint="http://127.0.0.1:8000/tts",
        field_mappings={"text": "text"},
        response_mode=HttpSpeechResponseMode.URL,
        response_field="audio_url",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = LocalHttpSpeechProvider(config=config, client=client)
        with pytest.raises(SpeechRequestError, match="loopback"):
            await provider.synthesize(SpeechSynthesisRequest(text="hello", voice_id="v"))


@pytest.mark.parametrize(
    ("field_mappings", "message"),
    [
        ({"__class__": "payload"}, "Unsupported request field"),
        ({"text": "nested.payload"}, "vendor field"),
    ],
)
def test_config_rejects_undeclared_or_executable_style_field_mapping(
    field_mappings: dict[str, str],
    message: str,
) -> None:
    with pytest.raises(SpeechConfigurationError, match=message):
        GenericHttpSpeechProvider(
            config=HttpSpeechProviderConfig(
                name="custom",
                model="v1",
                endpoint="https://tts.example.com/synth",
                field_mappings=field_mappings,
            )
        )


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
async def test_http_provider_normalizes_status_errors(
    status_code: int,
    error_type: type[Exception],
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text="vendor error")

    config = HttpSpeechProviderConfig(
        name="custom",
        model="v1",
        endpoint="https://tts.example.com/synth",
        field_mappings={"text": "text"},
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(error_type):
            await GenericHttpSpeechProvider(config=config, client=client).synthesize(
                SpeechSynthesisRequest(text="hello", voice_id="voice")
            )


@pytest.mark.asyncio
async def test_http_provider_normalizes_network_errors() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    config = HttpSpeechProviderConfig(
        name="custom",
        model="v1",
        endpoint="https://tts.example.com/synth",
        field_mappings={"text": "text"},
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SpeechRequestError, match="offline"):
            await GenericHttpSpeechProvider(config=config, client=client).synthesize(
                SpeechSynthesisRequest(text="hello", voice_id="voice")
            )

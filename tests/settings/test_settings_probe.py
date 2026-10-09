import json

import httpx
import pytest

from clipatlas.settings.probe import ServiceProbe, ServiceProbeRequest


def _request(
    *,
    service: str = "video",
    provider: str = "qwen",
    base_url: str = "https://provider.example/v1",
    model: str = "model-a",
    dimensions: int | None = None,
) -> ServiceProbeRequest:
    return ServiceProbeRequest(
        service=service,
        provider=provider,
        api_key="test-secret",
        base_url=base_url,
        model=model,
        dimensions=dimensions,
    )


@pytest.mark.asyncio
async def test_video_probe_uses_minimal_openai_compatible_request() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    probe = ServiceProbe(transport=httpx.MockTransport(handler))
    result = await probe.test_connection(_request())

    assert result.ok is True
    assert result.code == "ok"
    assert len(captured) == 1
    assert captured[0].url.path == "/v1/chat/completions"
    assert captured[0].headers["authorization"] == "Bearer test-secret"
    payload = json.loads(captured[0].content)
    assert payload["model"] == "model-a"
    assert payload["messages"][0]["content"] == "ping"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [
        (401, "auth_failed"),
        (403, "forbidden"),
        (404, "not_found"),
        (429, "rate_limited"),
    ],
)
async def test_probe_maps_common_http_failures(status_code: int, expected_code: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"error": {"message": "upstream error"}})

    probe = ServiceProbe(transport=httpx.MockTransport(handler))
    result = await probe.test_connection(_request())

    assert result.ok is False
    assert result.code == expected_code


@pytest.mark.asyncio
async def test_probe_maps_timeout_without_leaking_secret() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    probe = ServiceProbe(transport=httpx.MockTransport(handler))
    result = await probe.test_connection(_request())

    assert result.ok is False
    assert result.code == "timeout"
    assert "test-secret" not in result.message


@pytest.mark.asyncio
async def test_embedding_probe_uses_embedding_endpoint_and_dimensions() -> None:
    captured_payload: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_payload.update(json.loads(request.content))
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.0] * 1024}]})

    probe = ServiceProbe(transport=httpx.MockTransport(handler))
    result = await probe.test_connection(
        _request(service="embedding", provider="qwen-embedding", model="embed-a", dimensions=1024)
    )

    assert result.ok is True
    assert captured_payload == {
        "model": "embed-a",
        "input": ["ping"],
        "dimensions": 1024,
    }


@pytest.mark.asyncio
async def test_speech_probe_treats_voice_validation_as_reachable_but_model_error_as_failure() -> None:
    responses = iter(
        [
            httpx.Response(422, json={"message": "voice is required"}),
            httpx.Response(400, json={"message": "model not found"}),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return next(responses)

    probe = ServiceProbe(transport=httpx.MockTransport(handler))
    request = _request(
        service="speech",
        provider="dashscope",
        base_url="https://provider.example/api/v1/services/audio/tts/SpeechSynthesizer",
        model="voice-model",
    )

    reachable = await probe.test_connection(request)
    missing_model = await probe.test_connection(request)

    assert reachable.ok is True
    assert reachable.code == "ok"
    assert "音色" in reachable.message
    assert missing_model.ok is False
    assert missing_model.code == "model_unavailable"


@pytest.mark.asyncio
async def test_dashscope_speech_probe_normalizes_compatible_url_to_native_tts_endpoint() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(422, json={"message": "voice is required"})

    probe = ServiceProbe(transport=httpx.MockTransport(handler))
    result = await probe.test_connection(
        _request(
            service="speech",
            provider="dashscope",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="cosyvoice-v3.5-flash",
        )
    )

    assert result.ok is True
    assert captured[0].url.path == "/api/v1/services/audio/tts/SpeechSynthesizer"


@pytest.mark.asyncio
async def test_dashscope_speech_probe_treats_engine_voice_validation_as_connected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"message": "[cosyvoice:]Engine return error code: 418"},
        )

    result = await ServiceProbe(transport=httpx.MockTransport(handler)).test_connection(
        _request(service="speech", provider="dashscope")
    )

    assert result.ok is True
    assert result.code == "ok"


@pytest.mark.asyncio
async def test_model_listing_is_optional_and_keeps_unsupported_providers_manual() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        return httpx.Response(
            200,
            json={"data": [{"id": "model-b"}, {"id": "model-a"}]},
        )

    probe = ServiceProbe(transport=httpx.MockTransport(handler))
    supported = await probe.list_models(_request())
    unsupported = await probe.list_models(
        _request(
            service="speech",
            provider="dashscope",
            base_url="https://provider.example/api/v1/services/audio/tts/SpeechSynthesizer",
        )
    )

    assert supported.supported is True
    assert supported.models == ["model-a", "model-b"]
    assert unsupported.supported is False
    assert unsupported.models == []

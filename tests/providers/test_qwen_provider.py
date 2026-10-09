import base64
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from clipatlas.providers.contracts import AnalyzeSegmentRequest
from clipatlas.providers.errors import (
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderRequestError,
)
from clipatlas.providers.qwen import QwenVideoUnderstandingProvider


def _request(frame_uri: str, *, context: dict[str, object] | None = None,
             frame_times: list[int] | None = None) -> AnalyzeSegmentRequest:
    return AnalyzeSegmentRequest(
        video_id=uuid4(),
        segment_id=uuid4(),
        start_ms=1_000,
        end_ms=4_000,
        source_uri="file:///media/source.mp4",
        frame_uris=[frame_uri],
        frame_timestamps_ms=frame_times or [],
        context=context or {},
    )


def _success_payload(facts=None, *, english: bool = False) -> dict[str, object]:
    semantic = {
        "description": (
            "A man walks alone on a rainy city street at night."
            if english else "一名男子独自在雨夜的城市街道行走"
        ),
        "characters": ["adult man in dark coat"] if english else ["穿深色外套的成年男子"],
        "actions": ["walking alone", "looking down"] if english else ["独自行走", "低头"],
        "scene": ["city street", "night", "rain"] if english else ["城市街道", "夜晚", "雨天"],
        "emotions": ["lonely", "tired"] if english else ["孤独", "疲惫"],
        "objects": ["street lights", "cars"] if english else ["路灯", "汽车"],
        "ocr": [],
        "shot_type": "medium_long_shot",
        "camera_motion": "tracking",
        "confidence": 0.91,
        "facts": facts or [],
    }
    return {
        "id": "chatcmpl-test",
        "choices": [{"message": {"role": "assistant", "content": json.dumps(semantic)}}],
    }


@pytest.mark.asyncio
async def test_qwen_provider_uses_qwen38_and_structured_output_for_normal_segment(
    tmp_path: Path,
) -> None:
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"jpeg-bytes")
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_success_payload())

    provider = QwenVideoUnderstandingProvider(
        api_key="test-key",
        base_url="https://example.test/compatible-mode/v1",
        local_frame_root=tmp_path,
        transport=httpx.MockTransport(handler),
    )

    result = await provider.analyze_segment(_request(frame.as_uri()))

    assert provider.name == "qwen"
    assert provider.capabilities.image_input is True
    assert provider.capabilities.native_video_input is True
    assert provider.capabilities.structured_output is True
    assert result.model == "qwen3.8-flash"
    assert result.annotation.description.startswith("一名男子")
    assert result.annotation.actions == ["独自行走", "低头"]
    assert result.annotation.scene == ["城市街道", "夜晚", "雨天"]
    assert result.annotation.confidence == 0.91

    assert captured["url"] == "https://example.test/compatible-mode/v1/chat/completions"
    assert captured["authorization"] == "Bearer test-key"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["model"] == "qwen3.8-flash"
    assert body["enable_thinking"] is False
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True

    content = body["messages"][1]["content"]
    image_part = next(part for part in content if part["type"] == "image_url")
    expected = base64.b64encode(b"jpeg-bytes").decode("ascii")
    assert image_part["image_url"]["url"] == f"data:image/jpeg;base64,{expected}"


@pytest.mark.asyncio
async def test_qwen_repairs_english_semantics_once(tmp_path: Path) -> None:
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"jpeg")
    calls: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=_success_payload(english=len(calls) == 1))

    provider = QwenVideoUnderstandingProvider(
        api_key="key",
        base_url="https://example.test/v1",
        local_frame_root=tmp_path,
        transport=httpx.MockTransport(handler),
    )
    result = await provider.analyze_segment(_request(frame.as_uri()))

    assert len(calls) == 2
    assert "Translate only description" in calls[1]["messages"][-1]["content"]
    assert result.annotation.description == "一名男子独自在雨夜的城市街道行走"
    assert result.annotation.raw_payload["semantic_language"] == "zh-CN"


@pytest.mark.asyncio
async def test_qwen_keeps_english_semantics_when_translation_retry_fails(tmp_path: Path) -> None:
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"jpeg")
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_success_payload(english=True))

    provider = QwenVideoUnderstandingProvider(
        api_key="key",
        base_url="https://example.test/v1",
        local_frame_root=tmp_path,
        transport=httpx.MockTransport(handler),
    )
    result = await provider.analyze_segment(_request(frame.as_uri()))

    assert calls == 2
    assert result.annotation.description.startswith("A man walks alone")
    assert result.annotation.raw_payload["semantic_language"] == "english_fallback"
    assert "description" in result.annotation.raw_payload["semantic_language_issues"]


@pytest.mark.asyncio
async def test_qwen_provider_persists_typed_evidence_with_frame_provenance(tmp_path: Path) -> None:
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"jpeg")
    typed = [{
        "layer": "subject", "value": "BJ40", "evidence": "frame_0", "confidence": 0.9,
        "start_ms": 2000, "end_ms": 2000,
        "statement": {"proposition": {"subject": "BJ40", "predicate": "identity",
            "value": "BJ40", "unit": None, "scope": None, "polarity": "positive"},
            "entity_id": "car_1", "kind": "visual", "representation": "real_scene",
            "frame_ids": ["frame_0"], "temporal_basis": "point"},
    }]
    async def handler(request):
        return httpx.Response(200, json=_success_payload(typed))
    provider = QwenVideoUnderstandingProvider(api_key="key", base_url="https://test.invalid",
        local_frame_root=tmp_path, transport=httpx.MockTransport(handler))
    result = await provider.analyze_segment(_request(frame.as_uri(), frame_times=[2000]))
    statement = result.annotation.facts[0].statement
    assert statement is not None
    assert statement.proposition.value == "BJ40"
    assert statement.frame_ids == ["frame_0"]


@pytest.mark.asyncio
async def test_qwen_repairs_evidence_outside_observed_frame_time(tmp_path: Path) -> None:
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"jpeg")
    calls = 0
    requests: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        requests.append(json.loads(request.content))
        timestamp = 2001 if calls == 1 else 2000
        typed = [{
            "layer": "subject", "value": "人物", "start_ms": timestamp, "end_ms": timestamp,
            "statement": {"proposition": {"subject": "人物", "predicate": "presence",
                "value": "人物"}, "entity_id": "person_1", "kind": "visual",
                "representation": "real_scene", "frame_ids": ["frame_0"],
                "temporal_basis": "point"},
        }]
        return httpx.Response(200, json=_success_payload(typed))

    provider = QwenVideoUnderstandingProvider(api_key="key", base_url="https://test.invalid",
        local_frame_root=tmp_path, transport=httpx.MockTransport(handler))
    result = await provider.analyze_segment(_request(frame.as_uri(), frame_times=[2000]))

    assert calls == 2
    assert "uses 2001-2001ms" in requests[1]["messages"][-1]["content"]
    assert "referenced frames cover 2000-2000ms" in requests[1]["messages"][-1]["content"]
    assert result.annotation.facts[0].start_ms == 2000


@pytest.mark.asyncio
async def test_qwen_repair_prompt_explains_invalid_action_evidence(tmp_path: Path) -> None:
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"jpeg")
    requests: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        facts = None if len(requests) == 2 else [{
            "layer": "action", "value": "挥手", "start_ms": 2000, "end_ms": 2000,
            "statement": {"proposition": {"subject": "人物", "predicate": "action",
                "value": "挥手"}, "entity_id": "person_1", "kind": "visual",
                "representation": "real_scene", "frame_ids": ["frame_0"],
                "temporal_basis": "point"},
        }]
        return httpx.Response(200, json=_success_payload(facts))

    provider = QwenVideoUnderstandingProvider(api_key="key", base_url="https://test.invalid",
        local_frame_root=tmp_path, transport=httpx.MockTransport(handler))
    await provider.analyze_segment(_request(frame.as_uri(), frame_times=[2000]))

    assert "observed action requires an interval and multiple observed frames" in (
        requests[1]["messages"][-1]["content"]
    )


@pytest.mark.asyncio
async def test_qwen_discards_one_invalid_fact_after_repair(tmp_path: Path) -> None:
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"jpeg")
    calls = 0
    invalid_action = [{
        "layer": "action", "value": "挥手", "start_ms": 2000, "end_ms": 2000,
        "statement": {"proposition": {"subject": "人物", "predicate": "action",
            "value": "挥手"}, "entity_id": "person_1", "kind": "visual",
            "representation": "real_scene", "frame_ids": ["frame_0"],
            "temporal_basis": "point"},
    }]

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_success_payload(invalid_action))

    provider = QwenVideoUnderstandingProvider(api_key="key", base_url="https://test.invalid",
        local_frame_root=tmp_path, transport=httpx.MockTransport(handler))
    result = await provider.analyze_segment(_request(frame.as_uri(), frame_times=[2000]))

    assert calls == 2
    assert result.annotation.facts == []


@pytest.mark.asyncio
async def test_qwen_provider_accepts_windows_drive_file_uri_inside_cache_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    # Use a real drive URI on Windows; emulate the drive directory only on POSIX.
    cache_root = (tmp_path / "cache" if tmp_path.drive
                  else tmp_path / "D:" / "ClipAtlas" / "data" / "library-cache")
    frame = cache_root / "item" / "frames" / "frame.jpg"
    frame.parent.mkdir(parents=True)
    frame.write_bytes(b"windows-jpeg")
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_success_payload())

    provider = QwenVideoUnderstandingProvider(
        api_key="test-key",
        base_url="https://example.test/v1",
        local_frame_root=cache_root,
        transport=httpx.MockTransport(handler),
    )

    await provider.analyze_segment(
        _request(frame.as_uri() if tmp_path.drive
                 else "file:///D:/ClipAtlas/data/library-cache/item/frames/frame.jpg")
    )

    body = captured["body"]
    assert isinstance(body, dict)
    content = body["messages"][1]["content"]
    image_part = next(part for part in content if part["type"] == "image_url")
    expected = base64.b64encode(b"windows-jpeg").decode("ascii")
    assert image_part["image_url"]["url"] == f"data:image/jpeg;base64,{expected}"


@pytest.mark.asyncio
async def test_qwen_provider_routes_whole_video_or_large_context_to_qwen38(tmp_path: Path) -> None:
    frame = tmp_path / "frame.png"
    frame.write_bytes(b"png")
    models: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        models.append(body["model"])
        return httpx.Response(200, json=_success_payload())

    provider = QwenVideoUnderstandingProvider(
        api_key="test-key",
        base_url="https://example.test/v1",
        local_frame_root=tmp_path,
        transport=httpx.MockTransport(handler),
    )

    whole_video = _request(frame.as_uri(), context={"analysis_scope": "whole_video"})
    large_context = _request(frame.as_uri(), context={"estimated_input_tokens": 300_000})

    assert (await provider.analyze_segment(whole_video)).model == "qwen3.8-flash"
    assert (await provider.analyze_segment(large_context)).model == "qwen3.8-flash"
    assert models == ["qwen3.8-flash", "qwen3.8-flash"]


@pytest.mark.asyncio
async def test_qwen_provider_rejects_local_frames_outside_configured_cache_root(
    tmp_path: Path,
) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "secret.jpg"
    outside.write_bytes(b"secret")
    provider = QwenVideoUnderstandingProvider(
        api_key="test-key",
        base_url="https://example.test/v1",
        local_frame_root=allowed,
    )

    with pytest.raises(ProviderRequestError, match="outside configured local frame root"):
        await provider.analyze_segment(_request(outside.as_uri()))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [
        (401, ProviderAuthenticationError),
        (429, ProviderRateLimitError),
        (500, ProviderRequestError),
    ],
)
async def test_qwen_provider_normalizes_http_errors(
    tmp_path: Path,
    status_code: int,
    expected_error: type[Exception],
) -> None:
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"jpeg")

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"error": {"message": "upstream failed"}})

    provider = QwenVideoUnderstandingProvider(
        api_key="test-key",
        base_url="https://example.test/v1",
        local_frame_root=tmp_path,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(expected_error, match="upstream failed"):
        await provider.analyze_segment(_request(frame.as_uri()))

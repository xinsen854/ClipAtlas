import base64
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from clipatlas.providers.contracts import AnalyzeSegmentRequest
from clipatlas.providers.deepseek import DeepSeekVisionUnderstandingProvider
from clipatlas.providers.errors import (
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderStructuredOutputError,
)
from clipatlas.providers.zhipu import GLMVideoUnderstandingProvider


def _request(frame_uris=None, *, context=None, frame_times=None) -> AnalyzeSegmentRequest:
    return AnalyzeSegmentRequest(
        video_id=uuid4(),
        segment_id=uuid4(),
        start_ms=1_000,
        end_ms=4_000,
        source_uri="https://media.example.com/clip.mp4",
        frame_uris=frame_uris or [],
        frame_timestamps_ms=frame_times or [],
        context=context or {},
    )


def _success_payload(facts=None, *, english: bool = False) -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "description": (
                                "An off-road vehicle drives on a muddy road"
                                if english else "越野车在泥地路面行驶"
                            ),
                            "characters": [],
                            "actions": ["off-road driving"] if english else ["越野行驶"],
                            "scene": ["muddy road"] if english else ["泥地路面"],
                            "emotions": [],
                            "objects": ["off-road vehicle"] if english else ["越野车"],
                            "ocr": [],
                            "shot_type": "medium_shot",
                            "camera_motion": "tracking",
                            "confidence": 0.9,
                            "query_relevance_score": 0.8,
                            "query_relevance_reason": "含越野车与泥地动作",
                            "facts": facts or [],
                        },
                        ensure_ascii=False,
                    )
                }
            }
        ]
    }


@pytest.mark.asyncio
async def test_zhipu_glm_sends_native_video_when_no_frames(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json=_success_payload())

    provider = GLMVideoUnderstandingProvider(
        api_key="fixture",
        local_frame_root=tmp_path,
        transport=httpx.MockTransport(handler),
    )

    result = await provider.analyze_segment(
        _request(context={"analysis_scope": "whole_video"})
    )

    assert provider.name == "zhipu-glm"
    assert provider.capabilities.native_video_input is True
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["model"] == "glm-4.1v-thinking-flash"
    assert payload["response_format"] == {"type": "json_object"}
    user_content = payload["messages"][1]["content"]
    assert any(part.get("type") == "video_url" for part in user_content)
    assert result.annotation.description == "越野车在泥地路面行驶"
    assert result.query_relevance_score == 0.8


@pytest.mark.asyncio
async def test_deepseek_requires_frames_and_sends_images(tmp_path: Path) -> None:
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"\xff\xd8fixture")
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json=_success_payload())

    provider = DeepSeekVisionUnderstandingProvider(
        api_key="fixture",
        local_frame_root=tmp_path,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderRequestError, match="frame"):
        await provider.analyze_segment(_request())

    result = await provider.analyze_segment(_request([frame.as_uri()]))

    assert provider.name == "deepseek-vision"
    assert provider.capabilities.native_video_input is False
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["model"] == "deepseek-v4-flash-vision-exp"
    user_content = payload["messages"][1]["content"]
    image_url = next(
        part["image_url"]["url"]
        for part in user_content
        if part.get("type") == "image_url"
    )
    assert image_url.startswith("data:image/jpeg;base64,")
    assert result.annotation.provider == "deepseek-vision"


@pytest.mark.asyncio
async def test_openai_compatible_provider_persists_same_typed_evidence_contract(tmp_path: Path) -> None:
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"jpeg")
    typed = [{
        "layer": "subject", "value": "BJ40", "start_ms": 2000, "end_ms": 2000,
        "statement": {"proposition": {"subject": "BJ40", "predicate": "identity",
            "value": "BJ40"}, "entity_id": "car_1", "kind": "visual",
            "representation": "real_scene", "frame_ids": ["frame_0"],
            "temporal_basis": "point"},
    }]
    async def handler(request):
        return httpx.Response(200, json=_success_payload(typed))
    provider = DeepSeekVisionUnderstandingProvider(api_key="key", local_frame_root=tmp_path,
                                                    transport=httpx.MockTransport(handler))
    result = await provider.analyze_segment(_request([frame.as_uri()], frame_times=[2000]))
    assert result.annotation.facts[0].statement.proposition.value == "BJ40"


@pytest.mark.asyncio
async def test_provider_repairs_invalid_json_once(tmp_path: Path) -> None:
    calls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})
        return httpx.Response(200, json=_success_payload())

    provider = GLMVideoUnderstandingProvider(
        api_key="fixture",
        local_frame_root=tmp_path,
        transport=httpx.MockTransport(handler),
    )

    result = await provider.analyze_segment(_request(context={"analysis_scope": "whole_video"}))

    assert result.annotation.description == "越野车在泥地路面行驶"
    assert len(calls) == 2
    assert "previous response was invalid" in calls[1]["messages"][-1]["content"]


@pytest.mark.asyncio
async def test_openai_compatible_provider_translates_english_semantics_once(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=_success_payload(english=len(calls) == 1))

    provider = GLMVideoUnderstandingProvider(
        api_key="fixture",
        local_frame_root=tmp_path,
        transport=httpx.MockTransport(handler),
    )
    result = await provider.analyze_segment(_request(context={"analysis_scope": "whole_video"}))

    assert len(calls) == 2
    assert "Translate only description" in calls[1]["messages"][-1]["content"]
    assert result.annotation.description == "越野车在泥地路面行驶"
    assert result.annotation.raw_payload["semantic_language"] == "zh-CN"


@pytest.mark.asyncio
async def test_provider_raises_after_two_invalid_attempts(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})

    provider = DeepSeekVisionUnderstandingProvider(
        api_key="fixture",
        local_frame_root=tmp_path,
        transport=httpx.MockTransport(handler),
    )
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"fixture")

    with pytest.raises(ProviderStructuredOutputError, match="repair retry"):
        await provider.analyze_segment(_request([frame.as_uri()]))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected"),
    [(401, ProviderAuthenticationError), (429, ProviderRateLimitError), (500, ProviderRequestError)],
)
async def test_provider_maps_upstream_errors(tmp_path: Path, status: int, expected: type[Exception]) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": "upstream trouble"}})

    provider = GLMVideoUnderstandingProvider(
        api_key="fixture",
        local_frame_root=tmp_path,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(expected):
        await provider.analyze_segment(_request(context={"analysis_scope": "whole_video"}))


@pytest.mark.asyncio
async def test_local_frame_outside_root_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.jpg"
    outside.write_bytes(b"fixture")
    provider = DeepSeekVisionUnderstandingProvider(
        api_key="fixture",
        local_frame_root=tmp_path,
    )

    with pytest.raises(ProviderRequestError, match="outside configured"):
        await provider.analyze_segment(_request([outside.as_uri()]))

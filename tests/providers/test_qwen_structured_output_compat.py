import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from clipatlas.providers.contracts import AnalyzeSegmentRequest
from clipatlas.providers.errors import ProviderRequestError
from clipatlas.providers.qwen import QwenVideoUnderstandingProvider


def _request(frame_uri: str) -> AnalyzeSegmentRequest:
    return AnalyzeSegmentRequest(
        video_id=uuid4(),
        segment_id=uuid4(),
        start_ms=1_000,
        end_ms=4_000,
        source_uri="file:///media/source.mp4",
        frame_uris=[frame_uri],
        context={
            "analysis_scope": "segment",
            "query": "A product is being publicly validated.",
        },
    )


def _semantic() -> dict[str, object]:
    return {
        "description": "室内舞台正在举行汽车发布活动",
        "characters": [],
        "actions": ["观众观看"],
        "scene": ["室内舞台"],
        "emotions": ["专注"],
        "objects": ["SUV", "LED屏幕"],
        "ocr": ["700上市发布会"],
        "shot_type": "wide shot",
        "camera_motion": "static",
        "confidence": 1.0,
    }


@pytest.mark.asyncio
async def test_qwen_provider_accepts_singleton_list_wrapped_structured_object(
    tmp_path: Path,
) -> None:
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"jpeg")

    async def handler(_request: httpx.Request) -> httpx.Response:
        payload = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": json.dumps([_semantic()]),
                    }
                }
            ]
        }
        return httpx.Response(200, json=payload)

    provider = QwenVideoUnderstandingProvider(
        api_key="test-key",
        base_url="https://example.test/v1",
        local_frame_root=tmp_path,
        transport=httpx.MockTransport(handler),
    )

    result = await provider.analyze_segment(_request(frame.as_uri()))

    assert result.annotation.description.startswith("室内舞台")
    assert result.annotation.confidence == 1.0


@pytest.mark.asyncio
async def test_qwen_provider_exposes_top_k_query_relevance(tmp_path: Path) -> None:
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"jpeg")

    async def handler(request: httpx.Request) -> httpx.Response:
        request_payload = json.loads(request.content)
        properties = request_payload["response_format"]["json_schema"]["schema"][
            "properties"
        ]
        assert "query_relevance_score" in properties
        assert "query_relevance_reason" in properties

        semantic = {
            **_semantic(),
            "query_relevance_score": 0.91,
            "query_relevance_reason": (
                "The visible launch-stage scene directly supports public product validation."
            ),
        }
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(semantic),
                        }
                    }
                ]
            },
        )

    provider = QwenVideoUnderstandingProvider(
        api_key="test-key",
        base_url="https://example.test/v1",
        local_frame_root=tmp_path,
        transport=httpx.MockTransport(handler),
    )

    result = await provider.analyze_segment(_request(frame.as_uri()))

    assert result.query_relevance_score == pytest.approx(0.91)
    assert (
        result.query_relevance_reason
        == "The visible launch-stage scene directly supports public product validation."
    )


@pytest.mark.asyncio
async def test_qwen_provider_accepts_leaked_additional_properties_schema_keyword(
    tmp_path: Path,
) -> None:
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"jpeg")

    semantic = {
        **_semantic(),
        "query_relevance_score": 0.88,
        "query_relevance_reason": "The visible public launch directly supports the query.",
        "additionalProperties": False,
    }

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(semantic),
                        }
                    }
                ]
            },
        )

    provider = QwenVideoUnderstandingProvider(
        api_key="test-key",
        base_url="https://example.test/v1",
        local_frame_root=tmp_path,
        transport=httpx.MockTransport(handler),
    )

    result = await provider.analyze_segment(_request(frame.as_uri()))

    assert result.query_relevance_score == pytest.approx(0.88)
    assert result.annotation.description.startswith("室内舞台")


@pytest.mark.asyncio
async def test_qwen_provider_retries_once_when_structured_content_is_empty_list(
    tmp_path: Path,
) -> None:
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"jpeg")
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        content = [] if calls == 1 else {
            **_semantic(),
            "query_relevance_score": 0.86,
            "query_relevance_reason": "The visible launch event directly supports the query.",
        }
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(content),
                        }
                    }
                ]
            },
        )

    provider = QwenVideoUnderstandingProvider(
        api_key="test-key",
        base_url="https://example.test/v1",
        local_frame_root=tmp_path,
        transport=httpx.MockTransport(handler),
    )

    result = await provider.analyze_segment(_request(frame.as_uri()))

    assert calls == 2
    assert result.query_relevance_score == pytest.approx(0.86)
    assert result.annotation.description.startswith("室内舞台")


@pytest.mark.asyncio
async def test_invalid_response_retries_in_json_object_mode_with_field_instructions(tmp_path):
    frame=tmp_path/'frame.jpg'
    frame.write_bytes(b'jpeg')
    requests=[]
    async def handler(request):
        body=json.loads(request.content)
        requests.append(body)
        if len(requests)==1:
            return httpx.Response(200,json={'id':'bad-first','choices':[{'message':{'content':'[]'}}]})
        assert body['response_format']=={'type':'json_object'}
        assert 'ONE JSON object' in body['messages'][-1]['content']
        assert body['model']==requests[0]['model'] and body['enable_thinking'] is False
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(_semantic())}}]})
    provider=QwenVideoUnderstandingProvider(api_key='test-key',base_url='https://example.test/v1',
        local_frame_root=tmp_path,transport=httpx.MockTransport(handler))
    result=await provider.analyze_segment(_request(frame.as_uri()))
    assert len(requests)==2 and requests[0]['response_format']['type']=='json_schema'
    assert result.annotation.description==_semantic()['description']


@pytest.mark.asyncio
async def test_json_fence_is_unwrapped_without_a_second_model_request(tmp_path):
    frame=tmp_path/'frame.jpg'
    frame.write_bytes(b'jpeg')
    calls=[]
    async def handler(request):
        calls.append(request)
        return httpx.Response(200,json={'choices':[{'message':{'content':'```json\n'+json.dumps(_semantic())+'\n```'}}]})
    provider=QwenVideoUnderstandingProvider(api_key='test-key',base_url='https://example.test/v1',
        local_frame_root=tmp_path,transport=httpx.MockTransport(handler))
    assert (await provider.analyze_segment(_request(frame.as_uri()))).annotation.objects==['SUV','LED屏幕']
    assert len(calls)==1


@pytest.mark.asyncio
async def test_persistent_schema_failure_reports_fields_and_logs_response_without_key(tmp_path,caplog):
    from clipatlas.providers.errors import ProviderStructuredOutputError
    frame=tmp_path/'frame.jpg'
    frame.write_bytes(b'jpeg')
    calls=[]
    async def handler(request):
        calls.append(request)
        invalid={**_semantic(),'confidence':99,'actions':{'wrong':'type'},'unexpected':'secret-test-key'}
        return httpx.Response(200,json={'id':'fixture-response','choices':[{'message':{'content':json.dumps(invalid)}}]})
    provider=QwenVideoUnderstandingProvider(api_key='secret-test-key',base_url='https://example.test/v1',
        local_frame_root=tmp_path,transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderStructuredOutputError) as failure:
        await provider.analyze_segment(_request(frame.as_uri()))
    assert len(calls)==2
    assert 'actions:' in str(failure.value) and 'confidence:' in str(failure.value)
    assert 'fixture-response' in str(failure.value)
    assert 'content=' in caplog.text and 'confidence' in caplog.text
    assert 'secret-test-key' not in caplog.text and 'base64,' not in caplog.text


@pytest.mark.asyncio
async def test_qwen_provider_keeps_empty_annotation_after_one_retry_when_no_evidence_repeats(
    tmp_path: Path,
) -> None:
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"jpeg")
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "[]",
                        }
                    }
                ]
            },
        )

    provider = QwenVideoUnderstandingProvider(
        api_key="test-key",
        base_url="https://example.test/v1",
        local_frame_root=tmp_path,
        transport=httpx.MockTransport(handler),
    )

    result = await provider.analyze_segment(_request(frame.as_uri()))

    assert calls == 2
    assert result.annotation.description == ""
    assert result.annotation.facts == []


@pytest.mark.asyncio
async def test_qwen_provider_ignores_unrelated_extra_structured_field(
    tmp_path: Path,
) -> None:
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"jpeg")

    semantic = {
        **_semantic(),
        # AI 偶发附带未要求的附加字段（如导演分级等），应被忽略而不是让整段批注失败。
        "director_units": [{"text_range": "国庆", "beat_range": [0, 0]}],
        "director_importance": "S",
    }

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(semantic),
                        }
                    }
                ]
            },
        )

    provider = QwenVideoUnderstandingProvider(
        api_key="test-key",
        base_url="https://example.test/v1",
        local_frame_root=tmp_path,
        transport=httpx.MockTransport(handler),
    )

    result = await provider.analyze_segment(_request(frame.as_uri()))
    assert result.annotation.description == _semantic()["description"]


@pytest.mark.asyncio
async def test_qwen_provider_still_rejects_multi_item_structured_list(
    tmp_path: Path,
) -> None:
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"jpeg")

    async def handler(_request: httpx.Request) -> httpx.Response:
        payload = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": json.dumps([_semantic(), _semantic()]),
                    }
                }
            ]
        }
        return httpx.Response(200, json=payload)

    provider = QwenVideoUnderstandingProvider(
        api_key="test-key",
        base_url="https://example.test/v1",
        local_frame_root=tmp_path,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderRequestError, match="invalid structured semantics"):
        await provider.analyze_segment(_request(frame.as_uri()))

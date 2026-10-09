import json

import httpx
import pytest

from clipatlas.providers.errors import ProviderRequestError


def _response(content: object) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(content, ensure_ascii=False),
                    }
                }
            ]
        },
    )


def _analyzer(transport: httpx.MockTransport):
    try:
        from clipatlas.rules.analyzer import QwenRuleAnalyzer
    except ModuleNotFoundError:
        pytest.fail("clipatlas.rules.analyzer is not implemented yet")

    client = httpx.AsyncClient(transport=transport)
    return QwenRuleAnalyzer(
        api_key="test-key",
        base_url="https://example.test/v1",
        client=client,
    ), client


@pytest.mark.asyncio
async def test_qwen_rule_analyzer_returns_candidate_project_rules_without_rewriting_source() -> None:
    source = "Official Media字幕保留但旁白不要念；Model 700读成Model seven hundred。"

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["model"] == "qwen3.8-flash"
        assert payload["enable_thinking"] is False
        assert payload["response_format"]["type"] == "json_schema"
        assert source in payload["messages"][1]["content"]
        return _response(
            {
                "rules": [
                    {"kind": "speech_suppress", "match": "Official Media"},
                    {
                        "kind": "pronunciation",
                        "match": "Model 700",
                        "replacement": "Model seven hundred",
                    },
                ]
            }
        )

    analyzer, client = _analyzer(httpx.MockTransport(handler))
    try:
        result = await analyzer.analyze(source)
    finally:
        await client.aclose()

    assert result.source_text == source
    assert [rule.kind.value for rule in result.rules] == [
        "speech_suppress",
        "pronunciation",
    ]
    assert result.rules[0].match == "Official Media"
    assert result.rules[1].replacement == "Model seven hundred"


@pytest.mark.asyncio
async def test_qwen_rule_analyzer_accepts_all_existing_rule_kinds_as_candidates() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return _response(
            {
                "rules": [
                    {"kind": "pronunciation", "match": "A1", "replacement": "A one"},
                    {"kind": "speech_suppress", "match": "Brand"},
                    {"kind": "speech_replace", "match": "old", "replacement": "new"},
                    {"kind": "subtitle_replace", "match": "old title", "replacement": "new title"},
                    {"kind": "entity_alias", "match": "X", "replacement": "off-road SUV"},
                    {"kind": "semantic_hint", "hint": "prefer real off-road testing footage"},
                ]
            }
        )

    analyzer, client = _analyzer(httpx.MockTransport(handler))
    try:
        result = await analyzer.analyze("batch instructions")
    finally:
        await client.aclose()

    assert [rule.kind.value for rule in result.rules] == [
        "pronunciation",
        "speech_suppress",
        "speech_replace",
        "subtitle_replace",
        "entity_alias",
        "semantic_hint",
    ]


@pytest.mark.asyncio
async def test_qwen_rule_analyzer_rejects_invalid_structured_rule_output() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return _response(
            {
                "rules": [
                    {
                        "kind": "magic_rule",
                        "match": "anything",
                        "replacement": "invented behavior",
                    }
                ]
            }
        )

    analyzer, client = _analyzer(httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderRequestError, match="invalid structured output"):
            await analyzer.analyze("do something ambiguous")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_qwen_rule_analyzer_blank_input_returns_no_candidates_without_http_call() -> None:
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _response({"rules": []})

    analyzer, client = _analyzer(httpx.MockTransport(handler))
    try:
        result = await analyzer.analyze("   ")
    finally:
        await client.aclose()

    assert result.source_text == "   "
    assert result.rules == []
    assert calls == 0

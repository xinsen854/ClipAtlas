import importlib
import json
from typing import Any

import httpx
import pytest

from clipatlas.providers.errors import ProviderRequestError


def _intent_module():
    try:
        return importlib.import_module("clipatlas.retrieval.intent")
    except ModuleNotFoundError:
        pytest.fail("clipatlas.retrieval.intent is not implemented yet")


@pytest.mark.asyncio
async def test_qwen_intent_builder_returns_observable_generic_intent() -> None:
    module = _intent_module()
    QwenRetrievalIntentBuilder = module.QwenRetrievalIntentBuilder

    captured: dict[str, Any] = {}
    source_text = "This technology is becoming part of ordinary daily life."

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["json"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "meaning": [
                                        "the technology is being adopted in everyday use"
                                    ],
                                    "visual_queries": [
                                        "ordinary people using the product in daily environments",
                                        "the product being used during routine daily activities",
                                    ],
                                    "entities": [],
                                }
                            )
                        }
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        builder = QwenRetrievalIntentBuilder(
            api_key="formal-bailian-key",
            base_url=(
                "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
            ),
            client=client,
        )
        intent = await builder.build(source_text)

    assert intent.source_text == source_text
    assert intent.meaning == ["the technology is being adopted in everyday use"]
    assert intent.visual_queries == [
        "ordinary people using the product in daily environments",
        "the product being used during routine daily activities",
    ]
    assert intent.entities == []

    assert captured["url"] == (
        "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/"
        "chat/completions"
    )
    payload = captured["json"]
    assert payload["model"] == "qwen3.8-flash"
    assert payload["enable_thinking"] is False
    assert payload["response_format"]["type"] == "json_schema"
    assert source_text in payload["messages"][-1]["content"]


@pytest.mark.asyncio
async def test_qwen_intent_builder_accepts_omitted_optional_lists() -> None:
    module = _intent_module()
    QwenRetrievalIntentBuilder = module.QwenRetrievalIntentBuilder

    source_text = "A domestic product is entering broader public view."
    visual_query = "authoritative media coverage of the product in a formal public setting"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "visual_queries": [visual_query],
                                }
                            )
                        }
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        builder = QwenRetrievalIntentBuilder(
            api_key="formal-bailian-key",
            base_url="https://workspace.invalid/compatible-mode/v1",
            client=client,
        )
        intent = await builder.build(source_text)

    assert intent.source_text == source_text
    assert intent.meaning == []
    assert intent.visual_queries == [visual_query]
    assert intent.entities == []


@pytest.mark.asyncio
async def test_qwen_intent_builder_preserves_source_text_instead_of_model_rewrite() -> None:
    module = _intent_module()
    QwenRetrievalIntentBuilder = module.QwenRetrievalIntentBuilder

    source_text = "A public service is earning broader public trust."

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "meaning": ["public trust is increasing"],
                                    "visual_queries": [
                                        "members of the public actively using the service"
                                    ],
                                    "entities": [],
                                    "source_text": "MODEL MUST NOT REPLACE CANONICAL TEXT",
                                }
                            )
                        }
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        builder = QwenRetrievalIntentBuilder(
            api_key="formal-bailian-key",
            base_url="https://workspace.invalid/compatible-mode/v1",
            client=client,
        )
        intent = await builder.build(source_text)

    assert intent.source_text == source_text


@pytest.mark.asyncio
async def test_qwen_intent_builder_rejects_invalid_structured_output() -> None:
    module = _intent_module()
    QwenRetrievalIntentBuilder = module.QwenRetrievalIntentBuilder

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "meaning": "not-a-list",
                                    "visual_queries": ["observable scene"],
                                    "entities": [],
                                }
                            )
                        }
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        builder = QwenRetrievalIntentBuilder(
            api_key="formal-bailian-key",
            base_url="https://workspace.invalid/compatible-mode/v1",
            client=client,
        )
        with pytest.raises(ProviderRequestError, match="structured"):
            await builder.build("A generic abstract statement")


@pytest.mark.asyncio
async def test_qwen_intent_builder_limits_visual_queries_to_four() -> None:
    module = _intent_module()
    QwenRetrievalIntentBuilder = module.QwenRetrievalIntentBuilder

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "meaning": ["generic meaning"],
                                    "visual_queries": [
                                        "scene one",
                                        "scene two",
                                        "scene three",
                                        "scene four",
                                        "scene five",
                                    ],
                                    "entities": [],
                                }
                            )
                        }
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        builder = QwenRetrievalIntentBuilder(
            api_key="formal-bailian-key",
            base_url="https://workspace.invalid/compatible-mode/v1",
            client=client,
        )
        with pytest.raises(ProviderRequestError, match="structured"):
            await builder.build("Another generic abstract statement")

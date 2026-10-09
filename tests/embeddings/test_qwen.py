import json

import httpx
import pytest

from clipatlas.embeddings.qwen import QwenTextEmbeddingProvider
from clipatlas.providers.errors import (
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderRequestError,
)


@pytest.mark.asyncio
async def test_qwen_embedding_provider_posts_documents_and_preserves_index_order() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/embeddings")
        assert request.headers["Authorization"] == "Bearer test-key"
        body = json.loads(request.content)
        assert body == {
            "model": "text-embedding-v4",
            "input": ["雨夜独行", "城市人群"],
            "dimensions": 3,
        }
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.0, 1.0, 0.0]},
                    {"index": 0, "embedding": [1.0, 0.0, 0.0]},
                ],
                "model": "text-embedding-v4",
            },
        )

    provider = QwenTextEmbeddingProvider(
        api_key="test-key",
        base_url="https://dashscope.example/v1",
        dimensions=3,
        transport=httpx.MockTransport(handler),
    )

    vectors = await provider.embed_documents(["雨夜独行", "城市人群"])

    assert [vector.values for vector in vectors] == [
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
    ]
    assert provider.name == "qwen-embedding"
    assert provider.model == "text-embedding-v4"
    assert provider.dimensions == 3


@pytest.mark.asyncio
async def test_qwen_embedding_provider_embeds_query_with_same_contract() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["input"] == ["男人在雨里走路"]
        return httpx.Response(
            200,
            json={"data": [{"index": 0, "embedding": [0.2, 0.3, 0.4]}]},
        )

    provider = QwenTextEmbeddingProvider(
        api_key="test-key",
        base_url="https://dashscope.example/v1",
        dimensions=3,
        transport=httpx.MockTransport(handler),
    )

    vector = await provider.embed_query("男人在雨里走路")

    assert vector.values == [0.2, 0.3, 0.4]


@pytest.mark.asyncio
async def test_qwen_embedding_provider_rejects_wrong_dimensions() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [{"index": 0, "embedding": [1.0, 0.0]}]},
        )

    provider = QwenTextEmbeddingProvider(
        api_key="test-key",
        base_url="https://dashscope.example/v1",
        dimensions=3,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderRequestError, match="dimension"):
        await provider.embed_query("query")


@pytest.mark.asyncio
async def test_qwen_embedding_provider_rejects_non_finite_values() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b'{"data":[{"index":0,"embedding":[1.0,NaN,0.0]}]}',
            headers={"content-type": "application/json"},
        )

    provider = QwenTextEmbeddingProvider(
        api_key="test-key",
        base_url="https://dashscope.example/v1",
        dimensions=3,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderRequestError, match="finite"):
        await provider.embed_query("query")


@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [
        (401, ProviderAuthenticationError),
        (403, ProviderAuthenticationError),
        (429, ProviderRateLimitError),
        (500, ProviderRequestError),
    ],
)
@pytest.mark.asyncio
async def test_qwen_embedding_provider_normalizes_http_errors(
    status_code: int,
    error_type: type[Exception],
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            json={"error": {"message": "upstream failure"}},
        )

    provider = QwenTextEmbeddingProvider(
        api_key="test-key",
        base_url="https://dashscope.example/v1",
        dimensions=3,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(error_type, match="upstream failure"):
        await provider.embed_query("query")

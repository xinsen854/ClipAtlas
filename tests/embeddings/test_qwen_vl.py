import os
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from clipatlas.embeddings.qwen_vl import QwenVLVideoEmbeddingProvider
from clipatlas.providers.errors import (
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderRequestError,
)


class FakeVendorEmbedder:
    def __init__(
        self,
        *,
        values: list[float] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.values = values or [1.0] + [0.0] * 2559
        self.error = error
        self.video_calls: list[str] = []
        self.query_calls: list[str] = []

    def embed_video_chunk(self, path: str, verbose: bool = False) -> list[float]:
        self.video_calls.append(path)
        if self.error is not None:
            raise self.error
        return list(self.values)

    def embed_query(self, text: str, verbose: bool = False) -> list[float]:
        self.query_calls.append(text)
        if self.error is not None:
            raise self.error
        return list(self.values)


class RecordingFactory:
    def __init__(self, embedder: FakeVendorEmbedder) -> None:
        self.embedder = embedder
        self.calls: list[dict[str, Any]] = []
        self.visible_keys: list[str | None] = []

    def __call__(self, **kwargs: Any) -> FakeVendorEmbedder:
        self.calls.append(kwargs)
        self.visible_keys.append(os.environ.get("DASHSCOPE_API_KEY"))
        return self.embedder


@pytest.mark.asyncio
async def test_qwen_vl_delegates_video_and_query_to_vendored_core_at_2560_dimensions(
    tmp_path: Path,
) -> None:
    video = tmp_path / "chunk.mp4"
    video.write_bytes(b"video")
    vendor = FakeVendorEmbedder()
    factory = RecordingFactory(vendor)
    provider = QwenVLVideoEmbeddingProvider(
        api_key="test-key",
        embedder_factory=factory,
    )

    video_vector = await provider.embed_video(video)
    query_vector = await provider.embed_query("夜间山路")

    assert provider.name == "qwen-vl-video"
    assert provider.model == "qwen3-vl-embedding"
    assert provider.effective_dimensions == 2560
    assert factory.calls == [
        {
            "model_name": "qwen3-vl-embedding",
            "dimensions": 2560,
        }
    ]
    assert vendor.video_calls == [str(video.resolve())]
    assert vendor.query_calls == ["夜间山路"]
    assert len(video_vector.values) == 2560
    assert len(query_vector.values) == 2560


@pytest.mark.parametrize("previous_key", [None, "preexisting-key"])
def test_qwen_vl_exposes_key_only_during_vendor_construction_and_restores_environment(
    monkeypatch: pytest.MonkeyPatch,
    previous_key: str | None,
) -> None:
    if previous_key is None:
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    else:
        monkeypatch.setenv("DASHSCOPE_API_KEY", previous_key)
    factory = RecordingFactory(FakeVendorEmbedder())

    QwenVLVideoEmbeddingProvider(api_key="clipatlas-key", embedder_factory=factory)

    assert factory.visible_keys == ["clipatlas-key"]
    if previous_key is None:
        assert "DASHSCOPE_API_KEY" not in os.environ
    else:
        assert os.environ["DASHSCOPE_API_KEY"] == previous_key


def test_qwen_vl_sets_native_dashscope_base_before_vendor_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dashscope_module = ModuleType("dashscope")
    dashscope_module.base_http_api_url = "https://old.example/api/v1"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "dashscope", dashscope_module)
    factory = RecordingFactory(FakeVendorEmbedder())

    QwenVLVideoEmbeddingProvider(
        api_key="test-key",
        base_http_api_url="https://workspace.cn-beijing.maas.aliyuncs.com/api/v1/",
        embedder_factory=factory,
    )

    assert dashscope_module.base_http_api_url == (  # type: ignore[attr-defined]
        "https://workspace.cn-beijing.maas.aliyuncs.com/api/v1"
    )


@pytest.mark.asyncio
async def test_qwen_vl_rejects_returned_dimension_mismatch() -> None:
    factory = RecordingFactory(FakeVendorEmbedder(values=[1.0] + [0.0] * 767))
    provider = QwenVLVideoEmbeddingProvider(api_key="test-key", embedder_factory=factory)

    with pytest.raises(ProviderRequestError, match="2560"):
        await provider.embed_query("query")


@pytest.mark.asyncio
async def test_qwen_vl_rejects_missing_local_video_before_vendor_call(tmp_path: Path) -> None:
    vendor = FakeVendorEmbedder()
    provider = QwenVLVideoEmbeddingProvider(
        api_key="test-key",
        embedder_factory=RecordingFactory(vendor),
    )

    with pytest.raises(FileNotFoundError):
        await provider.embed_video(tmp_path / "missing.mp4")

    assert vendor.video_calls == []


@pytest.mark.parametrize(
    ("message", "error_type"),
    [
        (
            "DashScope API error (HTTP 401, code='InvalidApiKey'): denied",
            ProviderAuthenticationError,
        ),
        (
            "DashScope API error (HTTP 403, code='Forbidden'): denied",
            ProviderAuthenticationError,
        ),
        (
            "DashScope API error (HTTP 429, code='Throttling'): rate limited",
            ProviderRateLimitError,
        ),
        ("quota exhausted", ProviderRateLimitError),
        ("upstream HTTP 500", ProviderRequestError),
        ("connection reset by peer", ProviderRequestError),
    ],
)
@pytest.mark.asyncio
async def test_qwen_vl_normalizes_final_vendor_errors(
    message: str,
    error_type: type[Exception],
) -> None:
    provider = QwenVLVideoEmbeddingProvider(
        api_key="test-key",
        embedder_factory=RecordingFactory(FakeVendorEmbedder(error=RuntimeError(message))),
    )

    with pytest.raises(error_type, match=re.escape(message)):
        await provider.embed_query("query")


@pytest.mark.parametrize(
    "bad_value",
    [float("nan"), float("inf"), True],
)
@pytest.mark.asyncio
async def test_qwen_vl_rejects_non_finite_or_non_numeric_values(bad_value: object) -> None:
    values: list[Any] = [1.0] + [0.0] * 2559
    values[1] = bad_value
    provider = QwenVLVideoEmbeddingProvider(
        api_key="test-key",
        embedder_factory=RecordingFactory(FakeVendorEmbedder(values=values)),
    )

    with pytest.raises(ProviderRequestError, match="finite|numeric"):
        await provider.embed_query("query")

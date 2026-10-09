from uuid import UUID

import pytest

from clipatlas.retrieval.intent import RetrievalIntent
from clipatlas.retrieval.intent_search import IntentAwareHybridSearch


class EmptyHybridSearch:
    async def search(
        self,
        query: str,
        limit: int = 10,
        video_ids: list[UUID] | None = None,
    ):
        return []


class StubIntentBuilder:
    async def build(
        self,
        source_text: str,
        context: dict[str, object] | None = None,
    ) -> RetrievalIntent:
        return RetrievalIntent(source_text=source_text)


def _runtime_symbols():
    from clipatlas import app_state

    missing = [
        name
        for name in (
            "build_retrieval_intent_builder",
            "build_intent_aware_hybrid_search_service",
            "build_local_rough_cut_search_service",
        )
        if not hasattr(app_state, name)
    ]
    if missing:
        pytest.fail(f"retrieval intent runtime wiring is not implemented yet: {missing}")
    return (
        app_state.build_retrieval_intent_builder,
        app_state.build_intent_aware_hybrid_search_service,
        app_state.build_local_rough_cut_search_service,
    )


def test_intent_builder_requires_formal_bailian_credentials(monkeypatch) -> None:
    build_builder, _, _ = _runtime_symbols()

    monkeypatch.delenv("CLIPATLAS_BAILIAN_API_KEY", raising=False)
    monkeypatch.delenv("CLIPATLAS_BAILIAN_BASE_URL", raising=False)
    monkeypatch.setenv("CLIPATLAS_QWEN_API_KEY", "legacy-third-party-key")
    monkeypatch.setenv("CLIPATLAS_QWEN_BASE_URL", "https://third-party.invalid/v1")

    assert build_builder() is None

    monkeypatch.setenv("CLIPATLAS_BAILIAN_API_KEY", "formal-bailian-key")
    monkeypatch.setenv(
        "CLIPATLAS_BAILIAN_BASE_URL",
        "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    )

    builder = build_builder()

    assert builder is not None
    assert builder._api_key == "formal-bailian-key"
    assert (
        builder._base_url
        == "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    )


def test_intent_wrapper_feeds_the_local_rough_cut_search() -> None:
    _, build_wrapper, build_local_rough_cut = _runtime_symbols()

    plain_hybrid = EmptyHybridSearch()
    builder = StubIntentBuilder()
    wrapped = build_wrapper(plain_hybrid, builder=builder)

    assert isinstance(wrapped, IntentAwareHybridSearch)
    assert wrapped._search is plain_hybrid
    assert wrapped._builder is builder

    local = build_local_rough_cut(wrapped)

    assert local is not None
    assert local._search is wrapped


def test_runtime_falls_back_to_plain_hybrid_without_intent_builder() -> None:
    _, build_wrapper, _ = _runtime_symbols()

    plain_hybrid = EmptyHybridSearch()

    assert build_wrapper(plain_hybrid, builder=None) is plain_hybrid
    assert build_wrapper(None, builder=StubIntentBuilder()) is None

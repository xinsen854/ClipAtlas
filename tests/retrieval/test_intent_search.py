import importlib
from uuid import UUID, uuid4

import pytest

from clipatlas.providers.errors import ProviderRequestError
from clipatlas.retrieval.hybrid import HybridSearchHit
from clipatlas.retrieval.intent import RetrievalIntent


def _intent_search_module():
    try:
        return importlib.import_module("clipatlas.retrieval.intent_search")
    except ModuleNotFoundError:
        pytest.fail("clipatlas.retrieval.intent_search is not implemented yet")


class StubIntentBuilder:
    def __init__(
        self,
        *,
        visual_queries: list[str] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.visual_queries = visual_queries or []
        self.error = error
        self.calls: list[str] = []

    async def build(
        self,
        source_text: str,
        context: dict[str, object] | None = None,
    ) -> RetrievalIntent:
        self.calls.append(source_text)
        if self.error is not None:
            raise self.error
        return RetrievalIntent(
            source_text=source_text,
            meaning=["generic editorial meaning"],
            visual_queries=self.visual_queries,
            entities=[],
        )


class RecordingHybridSearch:
    def __init__(self, responses: dict[str, list[HybridSearchHit]]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, int, list[UUID] | None]] = []

    async def search(
        self,
        query: str,
        limit: int = 10,
        video_ids: list[UUID] | None = None,
    ) -> list[HybridSearchHit]:
        self.calls.append((query, limit, video_ids))
        return list(self.responses.get(query, []))


def _hit(
    *,
    video_id: UUID,
    start_ms: int,
    end_ms: int,
    score: float,
    suffix: str,
) -> HybridSearchHit:
    return HybridSearchHit(
        video_id=video_id,
        filename=f"video-{suffix}.mp4",
        source_uri=f"file:///video-{suffix}.mp4",
        source_start_ms=start_ms,
        source_end_ms=end_ms,
        score=score,
        visual_score=score,
        sources=["visual"],
    )


@pytest.mark.asyncio
async def test_roughcut_preserves_each_shot_query_even_with_lower_raw_score():
    module = _intent_search_module()
    studio = _hit(video_id=uuid4(), start_ms=0, end_ms=5000, score=0.99, suffix="studio")
    seats = _hit(video_id=uuid4(), start_ms=0, end_ms=5000, score=0.51, suffix="seats")
    driving = _hit(video_id=uuid4(), start_ms=0, end_ms=5000, score=0.65, suffix="driving")
    search = RecordingHybridSearch({"全句": [studio], "座椅特写": [seats], "越野行驶": [driving]})
    wrapper = module.IntentAwareHybridSearch(search=search, builder=StubIntentBuilder(
        visual_queries=["座椅特写", "越野行驶"]))
    result = await wrapper.search_with_context("全句", context={"rough_cut": True}, limit=2)
    assert [h.filename for h in result] == [seats.filename, driving.filename]
    assert [h.visual_query for h in result] == ["座椅特写", "越野行驶"]


@pytest.mark.asyncio
async def test_intent_search_keeps_original_query_and_adds_unique_visual_queries() -> None:
    module = _intent_search_module()
    IntentAwareHybridSearch = module.IntentAwareHybridSearch

    original = "An abstract statement about public confidence."
    visual_one = "people publicly using the service"
    visual_two = "a formal public demonstration of the service"
    builder = StubIntentBuilder(
        visual_queries=[visual_one, visual_one, "", visual_two]
    )
    search = RecordingHybridSearch({})
    wrapper = IntentAwareHybridSearch(search=search, builder=builder)
    video_ids = [uuid4()]

    await wrapper.search(original, limit=7, video_ids=video_ids)

    assert builder.calls == [original]
    assert search.calls == [
        (original, 7, video_ids),
        (visual_one, 7, video_ids),
        (visual_two, 7, video_ids),
    ]


@pytest.mark.asyncio
async def test_intent_search_deduplicates_same_range_and_keeps_best_existing_hit() -> None:
    module = _intent_search_module()
    IntentAwareHybridSearch = module.IntentAwareHybridSearch

    video_id = uuid4()
    original = "The product is being publicly validated."
    visual = "a public product demonstration"
    lower = _hit(
        video_id=video_id,
        start_ms=10_000,
        end_ms=15_000,
        score=0.42,
        suffix="lower",
    )
    higher = _hit(
        video_id=video_id,
        start_ms=10_000,
        end_ms=15_000,
        score=0.81,
        suffix="higher",
    )
    builder = StubIntentBuilder(visual_queries=[visual])
    search = RecordingHybridSearch({original: [lower], visual: [higher]})
    wrapper = IntentAwareHybridSearch(search=search, builder=builder)

    results = await wrapper.search(original, limit=10)

    assert len(results) == 1
    assert results[0] is higher
    assert results[0].score == 0.81
    assert results[0].filename == "video-higher.mp4"


@pytest.mark.asyncio
async def test_intent_search_limits_and_ranks_results_for_rough_cut() -> None:
    module = _intent_search_module()
    IntentAwareHybridSearch = module.IntentAwareHybridSearch

    original = "A generic abstract narration beat."
    visual = "observable activity that expresses the narration"
    first_id = uuid4()
    second_id = uuid4()
    third_id = uuid4()
    builder = StubIntentBuilder(visual_queries=[visual])
    search = RecordingHybridSearch(
        {
            original: [
                _hit(
                    video_id=first_id,
                    start_ms=0,
                    end_ms=5_000,
                    score=0.40,
                    suffix="first",
                ),
                _hit(
                    video_id=second_id,
                    start_ms=5_000,
                    end_ms=10_000,
                    score=0.90,
                    suffix="second",
                ),
            ],
            visual: [
                _hit(
                    video_id=third_id,
                    start_ms=10_000,
                    end_ms=15_000,
                    score=0.80,
                    suffix="third",
                )
            ],
        }
    )
    wrapper = IntentAwareHybridSearch(search=search, builder=builder)

    results = await wrapper.search(original, limit=2)

    assert len(results) == 2
    assert [result.score for result in results] == [0.90, 0.80]


@pytest.mark.asyncio
async def test_intent_search_fails_open_to_original_query_when_builder_raises() -> None:
    module = _intent_search_module()
    IntentAwareHybridSearch = module.IntentAwareHybridSearch

    original = "Keep the existing retrieval path available."
    video_id = uuid4()
    expected = _hit(
        video_id=video_id,
        start_ms=0,
        end_ms=5_000,
        score=0.55,
        suffix="fallback",
    )
    builder = StubIntentBuilder(
        error=ProviderRequestError("intent provider unavailable")
    )
    search = RecordingHybridSearch({original: [expected]})
    wrapper = IntentAwareHybridSearch(search=search, builder=builder)

    results = await wrapper.search(original, limit=3)

    assert results == [expected]
    assert search.calls == [(original, 3, None)]


@pytest.mark.asyncio
async def test_intent_search_uses_original_only_when_visual_queries_are_empty() -> None:
    module = _intent_search_module()
    IntentAwareHybridSearch = module.IntentAwareHybridSearch

    original = "A literal beat that needs no expansion."
    builder = StubIntentBuilder(visual_queries=[])
    search = RecordingHybridSearch({})
    wrapper = IntentAwareHybridSearch(search=search, builder=builder)

    await wrapper.search(original, limit=4)

    assert search.calls == [(original, 4, None)]

import json
from uuid import uuid4

import httpx
import pytest

from clipatlas.providers.errors import ProviderRequestError
from clipatlas.retrieval.hybrid import HybridSearchHit
from clipatlas.retrieval.intent import QwenRetrievalIntentBuilder
from clipatlas.retrieval.intent_search import IntentAwareHybridSearch
from clipatlas.retrieval.storyboard import ShotIntent, Storyboard, apply_storyboard, parse_storyboard
from clipatlas.roughcut.models import ScriptBeat


def beats(count=3):
    project, track = uuid4(), uuid4()
    return [ScriptBeat(project_id=project, narration_track_id=track, sequence=i,
                       text=f"原始文案{i}", query_text=f"原始文案{i}",
                       timeline_start_ms=i*4000, timeline_end_ms=(i+1)*4000,
                       target_duration_ms=4000) for i in range(count)]


def intent(start=0, end=0, **extra):
    return ShotIntent(start_sequence=start, end_sequence=end, subject="咖啡机", purpose="日常使用",
        evidence="visual", match_type="supporting", visual_queries=["咖啡机日常使用"],
        keywords=["咖啡"], alternatives=["咖啡机外观"], **extra)


def test_storyboard_groups_meaning_without_model_rewriting_text_or_timestamps():
    original = beats()
    result = apply_storyboard(original, Storyboard(shots=[intent(0, 1), intent(2, 2)]))
    assert [(b.timeline_start_ms, b.timeline_end_ms) for b in result] == [(0, 8000), (8000, 12000)]
    assert result[0].text == "原始文案0 原始文案1"
    assert result[0].retrieval_intent["match_type"] == "supporting"
    assert original[0].text == "原始文案0" and not original[0].retrieval_intent


@pytest.mark.parametrize("shots", [[intent(1, 2)], [intent(0, 1)], [intent(0, 1), intent(1, 2)]])
def test_missing_overlapping_reordered_and_overlong_groups_fail(shots):
    with pytest.raises(ProviderRequestError):
        apply_storyboard(beats(), Storyboard(shots=shots))


def test_overlong_group_splits_on_real_boundaries_and_json_wrappers_are_normalized():
    payload = Storyboard(shots=[intent(0, 4)])
    for content in [payload.model_dump_json(), json.dumps([payload.model_dump()]),
                    '```json\n' + json.dumps(payload.model_dump()['shots']) + '\n```']:
        result = apply_storyboard(beats(5), parse_storyboard(content))
        assert [b.target_duration_ms for b in result] == [16000, 4000]


@pytest.mark.asyncio
async def test_whole_script_uses_one_model_call_and_returns_sequential_groups():
    calls = []
    def respond(request):
        payload = json.loads(request.content); calls.append(payload)
        assert len(json.loads(payload["messages"][1]["content"])["units"]) == 3
        data = Storyboard(shots=[intent(0, 1), intent(2, 2)]).model_dump_json()
        return httpx.Response(200, json={"choices": [{"message": {"content": data}}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        builder = QwenRetrievalIntentBuilder(api_key="fixture", base_url="https://example.test", client=client)
        result = await builder.prepare_beats(beats(), {"semantic_hints": ["通用规则"]})
    assert len(calls) == 1
    assert [b.sequence for b in result] == [0, 1]


@pytest.mark.asyncio
async def test_planned_recall_and_fallback_do_not_call_per_sentence_intent_model():
    class NeverBuild:
        async def build(self, *args, **kwargs): raise AssertionError("No repeated model planning")
    class Search:
        def __init__(self): self.calls = []
        async def search_evidence(self, **kwargs):
            self.calls.append(kwargs)
            return [HybridSearchHit(video_id=uuid4(), filename="fixture.mp4", source_uri="file:///fixture.mp4",
                                    source_start_ms=0, source_end_ms=8000, score=0.03)]
    search = Search()
    wrapper = IntentAwareHybridSearch(search=search, builder=NeverBuild())
    context = {"rough_cut": True, "retrieval_intent": intent().model_dump(mode="json")}
    filters = [uuid4()]
    await wrapper.search_with_context("文案", context=context, video_ids=filters)
    await wrapper.search_with_context("文案", context={**context, "broaden_search": True}, video_ids=filters)
    assert [c["visual_queries"] for c in search.calls] == [["咖啡机日常使用"], ["咖啡机外观"]]
    assert all(c["keywords"] == ["咖啡"] and c["video_ids"] == filters for c in search.calls)

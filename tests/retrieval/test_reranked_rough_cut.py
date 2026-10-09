from copy import copy
from types import SimpleNamespace
from uuid import uuid4

from clipatlas.domain.models import AnnotationOrigin, SemanticAnnotation
from clipatlas.retrieval.reranked_rough_cut import RerankedRoughCutSearch


class _Inner:
    def __init__(self, hits, *, by_query=None):
        self.hits = hits
        self.by_query = by_query or {}
        self.calls = 0
        self.queries = []

    async def search_with_context(self, query, *, context=None, limit=12, video_ids=None):
        self.calls += 1
        self.queries.append(query)
        # Real retrieval returns fresh result objects for every call. Return
        # shallow copies here so the test double does not accidentally persist
        # wrapper-added ranking scores into the next logical snapshot.
        return [copy(hit) for hit in self.by_query.get(query, self.hits)]

    async def search(self, query, limit=12, video_ids=None):
        return [copy(hit) for hit in self.by_query.get(query, self.hits)]

    def project_video_ids(self, project_id):
        return []


class _Reranker:
    def __init__(self):
        self.calls = 0
        self.snapshots = []

    async def rank(self, candidates):
        self.calls += 1
        self.snapshots.append(list(candidates))
        result = {}
        for candidate in candidates:
            result.setdefault(candidate.requirement_id, []).append(candidate.candidate_id)
        for requirement_id in result:
            result[requirement_id] = list(reversed(result[requirement_id]))
        return result


def _hit(score: float, *, level: str = "DIRECT", video_id=None, start=1000, end=9000):
    segment_id = uuid4()
    return SimpleNamespace(
        segment_id=segment_id,
        video_id=video_id or uuid4(),
        source_start_ms=start,
        source_end_ms=end,
        score=score,
        hybrid_score=score,
        match_level=level,
        schedule_level="exact" if level == "DIRECT" else "related",
        pollution_level="clean",
        presentation_type="wide",
        protocol_id=None,
        protocol_candidate_type="legacy",
        anchor_start_ms=None,
        anchor_end_ms=None,
        query_relevance_reason="本地证据",
        annotation=SemanticAnnotation(
            segment_id=segment_id,
            origin=AnnotationOrigin.AI,
            description="泰钽700在贵州盘山路向上爬坡",
            characters=["泰钽700"], actions=["爬坡"], scene=["贵州盘山路"],
        ),
    )


async def test_reranked_search_changes_preference_without_changing_fact_level():
    first, second = _hit(0.90), _hit(0.80)
    reranker = _Reranker()
    search = RerankedRoughCutSearch(_Inner([first, second]), reranker=reranker)
    context = {
        "rough_cut": True,
        "director_importance": "S",
        "retrieval_intent": {"visual_requirements": [{
            "id": "r1", "sentence_id": "s1", "clause_id": "c1",
            "source_quote": "泰钽700在贵州盘山路向上爬坡",
            "source_text_hash": "h", "source_char_start": 0, "source_char_end": 14,
            "subject": "泰钽700", "action": "爬坡", "scene": "贵州盘山路",
            "environment": "贵州盘山路", "importance": "S",
        }]},
    }

    result = await search.search_with_context(
        "泰钽700在贵州盘山路向上爬坡", context=context, limit=12,
    )

    assert reranker.calls == 1
    assert result[0].segment_id == second.segment_id
    assert result[0].match_level == "DIRECT"
    assert result[1].match_level == "DIRECT"


async def test_reranked_search_is_cached_for_same_snapshot():
    hits = [_hit(0.90), _hit(0.80)]
    reranker = _Reranker()
    search = RerankedRoughCutSearch(_Inner(hits), reranker=reranker)
    context = {"rough_cut": True, "director_importance": "S"}

    await search.search_with_context("泰钽700爬坡", context=context, limit=12)
    await search.search_with_context("泰钽700爬坡", context=context, limit=12)

    assert reranker.calls == 1


async def test_reranker_not_used_for_b_level_or_single_candidate():
    reranker = _Reranker()
    one = RerankedRoughCutSearch(_Inner([_hit(0.9)]), reranker=reranker)
    await one.search_with_context(
        "过渡", context={"rough_cut": True, "director_importance": "S"}, limit=12,
    )
    assert reranker.calls == 0

    two = RerankedRoughCutSearch(_Inner([_hit(0.9), _hit(0.8)]), reranker=reranker)
    await two.search_with_context(
        "过渡", context={"rough_cut": True, "director_importance": "B"}, limit=12,
    )
    assert reranker.calls == 0


async def test_whole_script_prefetch_reranks_once_and_reserves_non_overlapping_sources():
    shared_video = uuid4()
    shared = _hit(0.95, video_id=shared_video, start=0, end=8000)
    first_alt = _hit(0.88, start=0, end=8000)
    second_unique = _hit(0.98, video_id=shared_video, start=0, end=8000)
    script = "泰钽700在贵州盘山路爬坡。随后车辆通过碎石路。"
    by_query = {
        "泰钽700在贵州盘山路爬坡。": [shared, first_alt],
        "随后车辆通过碎石路。": [second_unique],
    }
    inner = _Inner([shared, first_alt], by_query=by_query)
    reranker = _Reranker()
    search = RerankedRoughCutSearch(inner, reranker=reranker)
    context = {
        "rough_cut": True,
        "director_importance": "S",
        "narration_context": script,
        "retrieval_intent": {"visual_requirements": []},
    }

    result = await search.search_with_context(
        "泰钽700在贵州盘山路爬坡。", context=context, limit=12,
    )

    assert reranker.calls == 1
    assert len({c.requirement_id for c in reranker.snapshots[0]}) == 2
    assert result[0].video_id == first_alt.video_id
    assert "全局素材预留" in result[0].query_relevance_reason


async def test_whole_script_global_reservation_cache_avoids_repeat_prefetch():
    first = _hit(0.9)
    second = _hit(0.8)
    script = "泰钽700爬坡。车辆通过碎石路。"
    inner = _Inner([first, second])
    reranker = _Reranker()
    search = RerankedRoughCutSearch(inner, reranker=reranker)
    context = {
        "rough_cut": True,
        "director_importance": "S",
        "narration_context": script,
        "retrieval_intent": {"visual_requirements": []},
    }

    await search.search_with_context("泰钽700爬坡。", context=context, limit=12)
    calls_after_first = inner.calls
    await search.search_with_context("车辆通过碎石路。", context=context, limit=12)

    assert reranker.calls == 1
    assert inner.calls == calls_after_first + 1

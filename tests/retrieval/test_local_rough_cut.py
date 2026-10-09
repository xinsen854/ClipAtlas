# -*- coding: utf-8 -*-
"""Tests for the fully-local rough-cut recall adapter.

The rough-cut stage must be zero-API: it reads permanent annotation facts
from the local catalog and never forwards per-beat queries to a cloud hybrid.
"""

from uuid import UUID, uuid4

import pytest

from clipatlas.domain.models import AnnotationOrigin, SemanticAnnotation
from clipatlas.director.models import DirectorUnit
from clipatlas.domain.evidence import EvidenceAlternative, Proposition, VisualClaim
from clipatlas.retrieval.local_rough_cut import LocalRoughCutSearch


class RecordingHybrid:
    def __init__(self, hits=None):
        self.hits = hits or []
        self.search_calls: list[tuple[str, int, list[UUID] | None]] = []
        self.context_calls: list[tuple[str, dict[str, object] | None]] = []
        self.prepare_calls: list[tuple[list[object], dict[str, object]]] = []

    async def prepare_beats(self, beats, context):
        self.prepare_calls.append((beats, context))
        return beats

    async def search(self, query, limit=10, video_ids=None):
        self.search_calls.append((query, limit, video_ids))
        return self.hits

    async def search_with_context(self, query, *, context=None, limit=10, video_ids=None):
        self.context_calls.append((query, context))
        return self.hits


class StubSegment:
    def __init__(self, start_ms=0, end_ms=8_000):
        self.id = uuid4()
        self.video_id = uuid4()
        self.start_ms = start_ms
        self.end_ms = end_ms


class StubVideo:
    def __init__(self, segment):
        self.id = segment.video_id
        self.filename = "footage.mp4"
        self.source_uri = "file:///media/footage.mp4"


class StubCatalog:
    """Local catalog fake exposing the keyword facts query used by the
    rough-cut adapter (search_annotations_by_keywords + get_segment + get_video)."""

    def __init__(self, segment, annotation):
        self._segment = segment
        self._annotation = annotation
        self._video = StubVideo(segment)

    def search_annotations_by_keywords(self, keywords, *, limit, video_ids=None):
        del keywords, limit, video_ids
        if self._annotation is None:
            return []
        return [(self._segment.id, self._annotation)]

    def get_segment(self, segment_id):
        if segment_id == self._segment.id:
            return self._segment
        return None

    def get_video(self, video_id):
        if video_id == self._video.id:
            return self._video
        return None

    def get_effective_annotation(self, segment_id):
        if segment_id == self._segment.id:
            return self._annotation
        return None

    def search_segments_by_filename(self, keywords, *, limit, video_ids=None):
        del keywords, limit, video_ids
        return []


def _annotation(segment_id: UUID) -> SemanticAnnotation:
    return SemanticAnnotation(
        segment_id=segment_id,
        origin=AnnotationOrigin.AI,
        provider="qwen",
        description="越野车在泥地路面行驶",
        actions=["越野行驶"],
        scene=["泥地路面"],
        objects=["越野车"],
        confidence=0.9,
    )


@pytest.mark.asyncio
async def test_prepare_beats_is_identity_without_forwarding() -> None:
    """Rough-cut must not run the old storyboard API: prepare_beats is a
    no-op passthrough and never touches the wrapped search."""
    hybrid = RecordingHybrid()
    service = LocalRoughCutSearch(search=hybrid)

    beats = [object(), object()]
    result = await service.prepare_beats(beats, {"rough_cut": True})

    assert result == beats
    assert hybrid.prepare_calls == []


@pytest.mark.asyncio
async def test_search_with_context_recalls_from_local_annotation_facts() -> None:
    segment = StubSegment()
    annotation = _annotation(segment.id)
    service = LocalRoughCutSearch(
        search=RecordingHybrid([_hit()]),
        catalog=StubCatalog(segment, annotation),
    )

    results = await service.search_with_context("越野性能", context={"rough_cut": True})

    assert len(results) == 1
    hit = results[0]
    assert hit.segment_id == segment.id
    assert hit.annotation is annotation
    assert hit.annotation.description == "越野车在泥地路面行驶"
    assert hit.schedule_level == "exact"


@pytest.mark.asyncio
async def test_story_evidence_seeds_the_cited_source_window() -> None:
    segment = StubSegment(start_ms=1_000, end_ms=6_000)
    service = LocalRoughCutSearch(
        search=RecordingHybrid(),
        catalog=StubCatalog(segment, None),
    )

    results = await service.search_with_context(
        "unrelated editorial wording",
        context={
            "rough_cut": True,
            "retrieval_intent": {
                "story_evidence": [{
                    "evidence_id": "visual:opening",
                    "kind": "visual",
                    "video_id": str(segment.video_id),
                    "segment_id": str(segment.id),
                    "start_ms": segment.start_ms,
                    "end_ms": segment.end_ms,
                    "text": "Observed source event",
                    "source_name": "footage.mp4",
                }],
            },
        },
        video_ids=[segment.video_id],
    )

    assert results
    assert results[0].video_id == segment.video_id
    assert results[0].segment_id == segment.id
    assert (results[0].source_start_ms, results[0].source_end_ms) == (1_000, 6_000)


@pytest.mark.asyncio
async def test_typed_partial_claim_recall_preserves_direct_candidate_priority() -> None:
    segment = StubSegment()
    annotation = SemanticAnnotation(
        segment_id=segment.id, origin="ai", description="BJ40车型展示", ocr=["BJ40 增程"],
    )
    claims = [
        VisualClaim(claim_id="model", source_quote="BJ40", any_of=[EvidenceAlternative(
            all_of=[Proposition(subject="BJ40", predicate="identity", value="BJ40")],
            allowed_kinds=["source_text"],
        )]),
        VisualClaim(claim_id="drone", source_quote="车载无人机", any_of=[EvidenceAlternative(
            all_of=[Proposition(subject="BJ40增程悦野飞行版", predicate="configuration",
                                value="车载无人机")], allowed_kinds=["visual", "source_text"],
        )]),
    ]
    unit = DirectorUnit(text_range="BJ40配备车载无人机", importance="S", topic="配置",
                        claims=claims, visual_goal="proof")
    service = LocalRoughCutSearch(
        search=RecordingHybrid(), catalog=StubCatalog(segment, annotation),
    )
    results = await service.search_with_context("BJ40配备车载无人机", context={
        "retrieval_intent": {"director_units": [unit.model_dump(mode="json")]},
        "director_importance": "S",
    })
    assert results[0].schedule_level == "related"
    assert results[0].score >= 0.85
    assert "BJ40=DIRECT" in results[0].query_relevance_reason
    assert "车载无人机=SUPPORT" in results[0].query_relevance_reason


@pytest.mark.asyncio
async def test_search_without_matching_facts_returns_no_candidates() -> None:
    segment = StubSegment()
    service = LocalRoughCutSearch(
        search=RecordingHybrid([_hit()]),
        catalog=StubCatalog(segment, None),
    )

    results = await service.search_with_context("越野性能")

    assert results == []


@pytest.mark.asyncio
async def test_search_without_catalog_returns_no_candidates() -> None:
    service = LocalRoughCutSearch(search=RecordingHybrid([_hit()]), catalog=None)

    results = await service.search_with_context("越野性能")

    assert results == []


@pytest.mark.asyncio
async def test_search_without_contextual_contract_stays_local() -> None:
    """Even the plain search() entry point must not hit the network: without
    local facts it returns nothing instead of forwarding to a cloud search."""
    hybrid = RecordingHybrid([_hit()])
    service = LocalRoughCutSearch(search=hybrid, catalog=None)

    results = await service.search("越野性能", limit=5)

    assert results == []
    assert hybrid.search_calls == []


@pytest.mark.asyncio
async def test_empty_query_or_scope_returns_no_candidates() -> None:
    hybrid = RecordingHybrid([_hit()])
    service = LocalRoughCutSearch(search=hybrid)

    assert await service.search("  ") == []
    assert await service.search("查询", video_ids=[]) == []
    assert hybrid.search_calls == []


def _hit(score=0.7):
    from clipatlas.retrieval.hybrid import HybridSearchHit

    return HybridSearchHit(
        video_id=uuid4(),
        filename="footage.mp4",
        source_uri="file:///media/footage.mp4",
        source_start_ms=1_000,
        source_end_ms=6_000,
        score=score,
    )

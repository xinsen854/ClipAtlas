"""Tests for the local recall degradation chain (clause recall + library fallback)."""

from uuid import UUID, uuid4

import pytest

from clipatlas.domain.models import AnnotationOrigin, SemanticAnnotation
from clipatlas.retrieval.hybrid import HybridSearchHit
from clipatlas.retrieval.local_rough_cut import LocalRoughCutSearch, split_clauses


class EvidenceHybrid:
    """Wrapped search exposing search_evidence; records evidence calls."""

    def __init__(self, main_hits=None, evidence_hits=None):
        self.main_hits = main_hits or []
        self.evidence_hits = evidence_hits or []
        self.evidence_calls: list[tuple[list[str], list[str], str]] = []

    async def search(self, query, limit=10, video_ids=None):
        return self.main_hits

    async def search_with_context(self, query, *, context=None, limit=10, video_ids=None):
        return self.main_hits

    async def search_evidence(self, *, visual_queries, keywords, evidence, limit=12, video_ids=None):
        del visual_queries
        self.evidence_calls.append((keywords, evidence, limit))
        return self.evidence_hits


class FallbackCatalog:
    def __init__(self, segments_by_video, annotations=None, filename_by_video=None, roles=None):
        self._segments = segments_by_video
        self._annotations = annotations or {}
        self._filenames = filename_by_video or {}
        self._roles = roles or {}

    def list_video_ids(self, *, limit=100, offset=0):
        del limit, offset
        return list(self._segments.keys())

    def list_segments(self, video_id, *, limit, offset, start_ms=None, end_ms=None):
        del limit, offset, start_ms, end_ms
        return self._segments.get(video_id, [])

    def get_effective_annotation(self, segment_id):
        return self._annotations.get(segment_id)

    def search_annotations_by_keywords(self, keywords, *, limit, video_ids=None):
        del limit, video_ids
        results = []
        for seg_id, ann in self._annotations.items():
            desc = (ann.description or "") + " " + " ".join(ann.objects or []) + " " + " ".join(ann.actions or []) + " " + " ".join(ann.scene or [])
            if any(kw and kw in desc for kw in keywords):
                results.append((seg_id, ann))
        return results

    def get_segment(self, segment_id):
        for segs in self._segments.values():
            for seg in segs:
                if seg.id == segment_id:
                    return seg
        return None

    def get_video(self, video_id):
        name = self._filenames.get(video_id, "fallback.mp4")
        return type("V", (), {
            "filename": name, "source_uri": f"file:///{video_id}.mp4",
            "fallback_role": self._roles.get(video_id, "normal"),
        })()

    def search_segments_by_filename(self, keywords, *, limit, video_ids=None):
        del limit, video_ids
        results = []
        for video_id, name in self._filenames.items():
            for seg in self._segments.get(video_id, []):
                if any(kw and kw in name for kw in keywords):
                    results.append((seg.id, video_id, seg.start_ms, seg.end_ms, name))
        return results


class Seg:
    def __init__(self, video_id, start_ms, end_ms):
        self.id = uuid4()
        self.video_id = video_id
        self.start_ms = start_ms
        self.end_ms = end_ms


def _hit(video_id, start, end, score=0.7) -> HybridSearchHit:
    return HybridSearchHit(
        video_id=video_id,
        filename="main.mp4",
        source_uri=f"file:///{video_id}.mp4",
        source_start_ms=start,
        source_end_ms=end,
        score=score,
    )


def _annotation(segment_id: UUID) -> SemanticAnnotation:
    return SemanticAnnotation(
        segment_id=segment_id,
        origin=AnnotationOrigin.AI,
        provider="qwen",
        description="座舱大屏展示",
        confidence=0.9,
    )


def test_split_clauses_filters_short_fragments() -> None:
    parts = split_clauses(
        "整车座舱达到母婴级0醛0苯标准，暴晒7小时后甲醛低至2.1微克，仅为十分之一。",
        limit=3,
    )
    assert len(parts) == 3
    assert "母婴级0醛0苯标准" in parts[0]


@pytest.mark.asyncio
async def test_chinese_script_recalls_preserved_english_annotation_locally() -> None:
    video = uuid4()
    segment = Seg(video, 1_000, 7_000)
    annotation = SemanticAnnotation(
        segment_id=segment.id,
        origin=AnnotationOrigin.AI,
        provider="qwen",
        description="An off-road vehicle drives on a muddy road beside the coast",
        actions=["off-road driving"],
        scene=["muddy road", "coast"],
        objects=["off-road vehicle"],
    )
    service = LocalRoughCutSearch(
        search=EvidenceHybrid(),
        catalog=FallbackCatalog({video: [segment]}, annotations={segment.id: annotation}),
    )

    results = await service.search("越野车在泥地行驶到海边", video_ids=[video])

    assert results
    assert results[0].annotation.description == annotation.description
    assert results[0].schedule_level == "exact"


@pytest.mark.asyncio
async def test_clause_recall_runs_locally_when_coverage_is_short() -> None:
    video = uuid4()
    short_seg = Seg(video, 1_000, 6_000)  # 5s annotation hit only
    extra = _hit(video, 20_000, 28_000)  # 8s clause evidence
    hybrid = EvidenceHybrid(main_hits=[], evidence_hits=[extra])
    catalog = FallbackCatalog(
        {video: [short_seg]},
        annotations={short_seg.id: _annotation(short_seg.id)},
    )
    service = LocalRoughCutSearch(search=hybrid, catalog=catalog)

    results = await service.search_with_context(
        "整车座舱达到母婴级0醛0苯标准，暴晒7小时后甲醛含量低至2.1微克每立方米。",
        context={"needed_duration_ms": 12_000, "minimum_shot_ms": 2_000},
    )

    assert hybrid.evidence_calls, "clause recall should have run"
    keywords = hybrid.evidence_calls[0][0]
    assert keywords, "clause keywords must not be empty"
    assert any("0醛0苯" in kw for kw in keywords)
    assert sum(r.source_end_ms - r.source_start_ms for r in results) >= 12_000


@pytest.mark.asyncio
async def test_library_fallback_used_when_still_short() -> None:
    video = uuid4()
    main = _hit(video, 1_000, 6_000)
    hybrid = EvidenceHybrid(main_hits=[main], evidence_hits=[])
    segment = Seg(video, 30_000, 44_000)
    catalog = FallbackCatalog(
        {video: [segment]},
        annotations={segment.id: _annotation(segment.id)},
    )
    service = LocalRoughCutSearch(search=hybrid, catalog=catalog)

    results = await service.search_with_context(
        "母婴级0醛0苯标准 甲醛含量 十分之一",
        context={"needed_duration_ms": 12_000, "minimum_shot_ms": 3_000},
    )

    sources = [r for r in results if r.schedule_level == "source"]
    assert sources, "library fallback should provide source-level coverage"
    assert any(r.source_end_ms - r.source_start_ms >= 12_000 for r in results)


@pytest.mark.asyncio
async def test_covered_ms_respects_excluded_ranges_and_triggers_degradation() -> None:
    """When all long main hits are already used by prior clips, the recall must
    degrade instead of silently reporting enough coverage."""
    video = uuid4()
    main = _hit(video, 1_000, 15_000)  # long, but excluded
    extra = _hit(video, 20_000, 28_000)  # 8s, free
    hybrid = EvidenceHybrid(main_hits=[main], evidence_hits=[extra])
    service = LocalRoughCutSearch(search=hybrid)

    results = await service.search_with_context(
        "整车座舱达到母婴级0醛0苯标准，暴晒7小时后甲醛含量低至2.1微克每立方米。",
        context={
            "needed_duration_ms": 12_000,
            "minimum_shot_ms": 2_000,
            "excluded_ranges": [{"video_id": str(video), "start_ms": 0, "end_ms": 16_000}],
        },
    )

    assert all(r.source_start_ms >= 16_000 or r.source_start_ms < 1_000 for r in results)
    assert hybrid.evidence_calls, "excluded coverage should trigger clause recall"
    assert sum(r.source_end_ms - r.source_start_ms for r in results) >= 8_000


@pytest.mark.asyncio
async def test_no_degradation_when_first_recall_is_sufficient() -> None:
    video = uuid4()
    long_seg = Seg(video, 1_000, 15_000)  # 14s annotation hit
    matching = SemanticAnnotation(
        segment_id=long_seg.id,
        origin=AnnotationOrigin.AI,
        provider="qwen",
        description="越野车在泥地路面行驶",
        actions=["越野行驶"],
        scene=["泥地路面"],
        objects=["越野车"],
        confidence=0.9,
    )
    hybrid = EvidenceHybrid(main_hits=[], evidence_hits=[])
    catalog = FallbackCatalog(
        {video: [long_seg]},
        annotations={long_seg.id: matching},
    )
    service = LocalRoughCutSearch(search=hybrid, catalog=catalog)

    results = await service.search_with_context(
        "越野车在泥地路面行驶",
        context={"needed_duration_ms": 10_000, "minimum_shot_ms": 2_000},
    )

    assert len(results) == 1
    assert hybrid.evidence_calls == []
    assert all(r.schedule_level == "exact" for r in results)


@pytest.mark.asyncio
async def test_fallback_respects_excluded_ranges() -> None:
    video = uuid4()
    main = _hit(video, 1_000, 6_000)
    hybrid = EvidenceHybrid(main_hits=[main], evidence_hits=[])
    used = Seg(video, 10_000, 14_000)  # overlaps excluded range -> skipped
    free = Seg(video, 20_000, 40_000)
    catalog = FallbackCatalog({video: [used, free]})
    service = LocalRoughCutSearch(search=hybrid, catalog=catalog)

    results = await service.search_with_context(
        "母婴级0醛0苯标准",
        context={
            "needed_duration_ms": 12_000,
            "minimum_shot_ms": 3_000,
            "excluded_ranges": [{"video_id": str(video), "start_ms": 9_000, "end_ms": 15_000}],
        },
    )

    fallback = [r for r in results if r.schedule_level == "source"]
    assert len(fallback) == 1
    assert fallback[0].source_start_ms == 20_000
    assert fallback[0].source_end_ms == 40_000

@pytest.mark.asyncio
async def test_generic_fallback_preferred_over_plain_source() -> None:
    generic_video = uuid4()
    plain_video = uuid4()
    generic_seg = Seg(generic_video, 5_000, 25_000)  # long calm b-roll
    plain_seg = Seg(plain_video, 1_000, 12_000)
    hybrid = EvidenceHybrid(main_hits=[], evidence_hits=[])
    catalog = FallbackCatalog(
        {generic_video: [generic_seg], plain_video: [plain_seg]},
        filename_by_video={generic_video: "通用空镜素材.mp4", plain_video: "产品讲解.mp4"},
        roles={generic_video: "generic"},
    )
    service = LocalRoughCutSearch(search=hybrid, catalog=catalog)

    results = await service.search_with_context(
        "国标来了告别话术忽悠",
        context={"needed_duration_ms": 12_000, "minimum_shot_ms": 3_000},
    )

    generic = [r for r in results if r.schedule_level == "generic"]
    assert len(generic) == 1
    assert generic[0].source_start_ms == 5_000
    assert "通用素材兜底" in generic[0].query_relevance_reason


@pytest.mark.asyncio
async def test_generic_fallback_skips_title_card_and_short_segments() -> None:
    video = uuid4()
    short_seg = Seg(video, 1_000, 3_500)  # below minimum 4s
    long_seg = Seg(video, 10_000, 30_000)
    hybrid = EvidenceHybrid(main_hits=[], evidence_hits=[])
    catalog = FallbackCatalog(
        {video: [short_seg, long_seg]},
        filename_by_video={video: "b-roll通用素材.mp4"},
        roles={video: "generic"},
    )
    service = LocalRoughCutSearch(search=hybrid, catalog=catalog)

    results = await service.search_with_context(
        "没有对应画面的段落",
        context={"needed_duration_ms": 10_000, "minimum_shot_ms": 4_000},
    )

    generic = [r for r in results if r.schedule_level == "generic"]
    assert len(generic) == 1
    assert generic[0].source_start_ms == 10_000

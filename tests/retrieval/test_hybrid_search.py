from pathlib import Path
from uuid import UUID, uuid4

import pytest

from clipatlas.asr.models import ASRTextMatch
from clipatlas.domain.models import VideoAsset
from clipatlas.ocr.models import OCRTextMatch
from clipatlas.retrieval.hybrid import HybridSearchService
from clipatlas.retrieval.search import CoarseVideoSearchHit


class FakeCatalog:
    def __init__(self, videos: list[VideoAsset]) -> None:
        self._videos = {video.id: video for video in videos}

    def get_video(self, video_id: UUID) -> VideoAsset | None:
        return self._videos.get(video_id)


class FakeVisualSearch:
    def __init__(self, hits: list[CoarseVideoSearchHit]) -> None:
        self.hits = hits
        self.video_ids_seen: list[UUID] | None = None

    async def search(self, query, limit=10, video_ids=None, profile=None):
        self.video_ids_seen = video_ids
        return self.hits[:limit]


class FakeASRStore:
    def __init__(self, hits: list[ASRTextMatch]) -> None:
        self.hits = hits
        self.video_ids_seen: list[UUID] | None = None

    def search_text(self, query, provider, model, *, limit, video_ids=None):
        self.video_ids_seen = video_ids
        return self.hits[:limit]


class FakeOCRStore:
    def __init__(self, hits: list[OCRTextMatch]) -> None:
        self.hits = hits
        self.video_ids_seen: list[UUID] | None = None

    def search_text(self, query, provider, model, *, limit, video_ids=None):
        self.video_ids_seen = video_ids
        return self.hits[:limit]


def _video(video_id: UUID, name: str = "movie.mp4") -> VideoAsset:
    return VideoAsset(
        id=video_id,
        filename=name,
        source_uri=(Path.cwd().resolve() / name).as_uri(),
        duration_ms=30_000,
        width=1920,
        height=1080,
        fps=25.0,
    )


def _visual(video: VideoAsset, start_ms: int, end_ms: int, score: float) -> CoarseVideoSearchHit:
    return CoarseVideoSearchHit(
        video_id=video.id,
        filename=video.filename,
        source_uri=video.source_uri,
        source_start_ms=start_ms,
        source_end_ms=end_ms,
        score=score,
        embedding_provider="qwen-vl",
        embedding_model="qwen3-vl-embedding",
        embedding_dimensions=2560,
        chunk_duration_ms=5_000,
        overlap_ms=1_000,
    )


@pytest.mark.asyncio
async def test_planned_hybrid_routes_keywords_and_fuses_ranks_without_repeating_synonym_votes():
    video = _video(uuid4())
    class Visual(FakeVisualSearch):
        async def search(self, query, **kwargs):
            assert query == "咖啡机日常使用"
            return await super().search(query, **kwargs)
    class Speech(FakeASRStore):
        def search_text(self, query, *args, **kwargs):
            assert query in {"咖啡", "机器"}
            return super().search_text(query, *args, **kwargs)
    speech = Speech([ASRTextMatch(video_id=video.id, start_ms=10000, end_ms=15000,
                                  text="咖啡机器", revision=1)])
    service = HybridSearchService(catalog=FakeCatalog([video]),
        visual=Visual([_visual(video, 0, 5000, 0.95)]), asr_store=speech, ocr_store=FakeOCRStore([]))
    results = await service.search_evidence(visual_queries=["咖啡机日常使用"],
                                           keywords=["咖啡", "机器"], evidence="asr")
    assert results[0].source_start_ms == 10000
    assert results[0].score == pytest.approx(2 / 61)
    assert results[0].sources == ["asr"] and results[0].visual_score is None
    visual_first = await service.search_evidence(visual_queries=["咖啡机日常使用"],
                                                 keywords=["咖啡"], evidence="visual")
    assert visual_first[0].source_start_ms == 0


@pytest.mark.asyncio
async def test_hybrid_merges_three_sources_and_does_not_double_count_visual_overlap() -> None:
    video = _video(uuid4())
    visual = FakeVisualSearch(
        [
            _visual(video, 0, 5_000, 0.8),
            _visual(video, 4_000, 9_000, 0.7),
        ]
    )
    asr = FakeASRStore(
        [
            ASRTextMatch(
                video_id=video.id,
                start_ms=4_500,
                end_ms=6_500,
                text="越野测试开始",
                revision=1,
            )
        ]
    )
    ocr = FakeOCRStore(
        [
            OCRTextMatch(
                video_id=video.id,
                start_ms=5_000,
                end_ms=10_000,
                text="越野测试",
                revision=1,
                interval_ms=5_000,
            )
        ]
    )
    service = HybridSearchService(
        catalog=FakeCatalog([video]),
        visual=visual,
        asr_store=asr,
        ocr_store=ocr,
    )

    hits = await service.search("越野测试", limit=10)

    assert len(hits) == 1
    hit = hits[0]
    assert (hit.source_start_ms, hit.source_end_ms) == (0, 10_000)
    assert hit.sources == ["visual", "asr", "ocr"]
    assert hit.visual_score == pytest.approx(0.8)
    assert hit.asr_score == pytest.approx(4 / 6)
    assert hit.ocr_score == pytest.approx(1.0)
    assert hit.score == pytest.approx(0.8 + 4 / 6 + 1.0)
    assert hit.asr_texts == ["越野测试开始"]
    assert hit.ocr_texts == ["越野测试"]


@pytest.mark.asyncio
async def test_hybrid_merges_at_1000ms_gap_but_not_beyond_it() -> None:
    video = _video(uuid4())
    visual = FakeVisualSearch([_visual(video, 0, 5_000, 0.6)])
    asr = FakeASRStore(
        [
            ASRTextMatch(
                video_id=video.id,
                start_ms=6_000,
                end_ms=7_000,
                text="越野",
                revision=1,
            ),
            ASRTextMatch(
                video_id=video.id,
                start_ms=8_001,
                end_ms=9_000,
                text="越野",
                revision=1,
            ),
        ]
    )
    service = HybridSearchService(
        catalog=FakeCatalog([video]),
        visual=visual,
        asr_store=asr,
        ocr_store=FakeOCRStore([]),
    )

    hits = await service.search("越野", limit=10)

    assert [(hit.source_start_ms, hit.source_end_ms) for hit in hits] == [
        (0, 7_000),
        (8_001, 9_000),
    ]


@pytest.mark.asyncio
async def test_hybrid_works_without_visual_and_propagates_video_filter() -> None:
    video = _video(uuid4())
    asr = FakeASRStore(
        [
            ASRTextMatch(
                video_id=video.id,
                start_ms=1_000,
                end_ms=2_000,
                text="越野测试",
                revision=1,
            )
        ]
    )
    ocr = FakeOCRStore([])
    service = HybridSearchService(
        catalog=FakeCatalog([video]),
        visual=None,
        asr_store=asr,
        ocr_store=ocr,
    )

    hits = await service.search("越野测试", limit=10, video_ids=[video.id])

    assert len(hits) == 1
    assert hits[0].sources == ["asr"]
    assert hits[0].score == pytest.approx(1.0)
    assert asr.video_ids_seen == [video.id]
    assert ocr.video_ids_seen == [video.id]


@pytest.mark.asyncio
async def test_hybrid_orders_by_score_then_timeline_deterministically() -> None:
    first = _video(uuid4(), "first.mp4")
    second = _video(uuid4(), "second.mp4")
    asr = FakeASRStore(
        [
            ASRTextMatch(
                video_id=first.id,
                start_ms=5_000,
                end_ms=6_000,
                text="前缀越野测试后缀",
                revision=1,
            ),
            ASRTextMatch(
                video_id=second.id,
                start_ms=2_000,
                end_ms=3_000,
                text="越野测试",
                revision=1,
            ),
        ]
    )
    service = HybridSearchService(
        catalog=FakeCatalog([first, second]),
        visual=None,
        asr_store=asr,
        ocr_store=FakeOCRStore([]),
    )

    hits = await service.search("越野测试", limit=10)

    assert [hit.video_id for hit in hits] == [second.id, first.id]
    assert hits[0].score > hits[1].score

"""Text-occupancy filtering tests for the rough-cut candidate pool (media-type-v2)."""
from __future__ import annotations

import pytest

from clipatlas.retrieval.local_rough_cut import (
    LocalRoughCutSearch,
    LocalRoughCutHit,
)
from clipatlas.domain.models import SemanticAnnotation, AnnotationOrigin

UID = "11111111-2222-4333-8444-555555555555"


class _FakeCatalog:
    def __init__(self, media: tuple | None) -> None:
        self._media = media

    def get_segment_media_type(self, segment_id):
        return self._media


def _hit(schedule_level: str = "exact") -> LocalRoughCutHit:
    return LocalRoughCutHit(
        segment_id=UID,
        video_id=UID,
        filename="clip.mp4",
        source_uri="file:///clip.mp4",
        source_start_ms=0,
        source_end_ms=4000,
        score=0.5,
        hybrid_score=0.5,
        annotation=SemanticAnnotation(
            segment_id=UID,
            origin=AnnotationOrigin.AI,
            provider="catalog",
            description="test",
            confidence=0.5,
        ),
        schedule_level=schedule_level,
    )


def test_skips_title_card() -> None:
    search = LocalRoughCutSearch.__new__(LocalRoughCutSearch)
    search._catalog = _FakeCatalog(("title_card", "media-type-v2", None, None))
    assert search._filter_non_editable([_hit()]) == []


def test_downranks_text_heavy_frame() -> None:
    search = LocalRoughCutSearch.__new__(LocalRoughCutSearch)
    search._catalog = _FakeCatalog(("scene", "media-type-v2", 0.45, 2))
    kept = search._filter_non_editable([_hit()])
    assert len(kept) == 1 and kept[0].schedule_level == "text_heavy"


def test_downranks_messy_multi_block_frame() -> None:
    search = LocalRoughCutSearch.__new__(LocalRoughCutSearch)
    search._catalog = _FakeCatalog(("scene", "media-type-v2", 0.22, 5))
    kept = search._filter_non_editable([_hit()])
    assert len(kept) == 1 and kept[0].schedule_level == "text_heavy"


def test_keeps_small_text_scene() -> None:
    search = LocalRoughCutSearch.__new__(LocalRoughCutSearch)
    search._catalog = _FakeCatalog(("scene", "media-type-v2", 0.05, 2))
    kept = search._filter_non_editable([_hit()])
    assert [str(h.segment_id) for h in kept] == [UID]


def test_unannotated_passes_through() -> None:
    search = LocalRoughCutSearch.__new__(LocalRoughCutSearch)
    search._catalog = _FakeCatalog(None)
    kept = search._filter_non_editable([_hit()])
    assert [str(h.segment_id) for h in kept] == [UID]


def test_source_fallback_cannot_bypass_media_filter() -> None:
    search = LocalRoughCutSearch.__new__(LocalRoughCutSearch)
    search._catalog = _FakeCatalog(("title_card", "media-type-v2", 0.9, 6))
    kept = search._filter_non_editable([_hit(schedule_level="source")])
    assert kept == []


UID2 = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _hit_with_ocr(ocr, segment_id=UID, schedule_level="exact") -> LocalRoughCutHit:
    return LocalRoughCutHit(
        segment_id=segment_id,
        video_id=segment_id,
        filename="clip.mp4",
        source_uri="file:///clip.mp4",
        source_start_ms=0,
        source_end_ms=4000,
        score=0.5,
        hybrid_score=0.5,
        annotation=SemanticAnnotation(
            segment_id=segment_id,
            origin=AnnotationOrigin.AI,
            provider="catalog",
            description="test",
            ocr=ocr,
            confidence=0.5,
        ),
        schedule_level=schedule_level,
    )


def test_skips_screen_capture() -> None:
    search = LocalRoughCutSearch.__new__(LocalRoughCutSearch)
    search._catalog = _FakeCatalog(("screen_capture", "v", 0.05, 1))
    assert search._filter_non_editable([_hit()]) == []


def test_skips_technical_chart() -> None:
    search = LocalRoughCutSearch.__new__(LocalRoughCutSearch)
    search._catalog = _FakeCatalog(("technical_chart", "v", 0.1, 2))
    assert search._filter_non_editable([_hit()]) == []


def test_black_screen_without_matching_words_is_dropped() -> None:
    search = LocalRoughCutSearch.__new__(LocalRoughCutSearch)
    search._catalog = _FakeCatalog(("title_card", "v", 0.12, 1))
    assert search._filter_non_editable([_hit()]) == []


def test_title_card_unknown_blocks_still_dropped() -> None:
    # 文本块指标缺失时不臆断为“少量字”，仍按 title_card 丢弃。
    search = LocalRoughCutSearch.__new__(LocalRoughCutSearch)
    search._catalog = _FakeCatalog(("title_card", "v", None, None))
    assert search._filter_non_editable([_hit()]) == []


def test_c_tail_sorted_after_normal() -> None:
    search = LocalRoughCutSearch.__new__(LocalRoughCutSearch)
    media = {
        UID: ("scene", "v", 0.05, 1),
        UID2: ("title_card", "v", 0.12, 1),
    }

    class _Catalog:
        def get_segment_media_type(self, segment_id):
            return media[str(segment_id)]

    search._catalog = _Catalog()
    tail = _hit_with_ocr(["累计用户突破200万"], segment_id=UID2)
    normal = _hit()
    kept = search._filter_non_editable(
        [tail, normal], {"match_keywords": ["200万", "用户"],
                         "allow_tail_text": True, "needed_duration_ms": 2000}
    )
    assert [str(h.segment_id) for h in kept] == [UID, UID2]
    assert kept[-1].schedule_level == "c_tail"


def test_matching_title_card_is_tail_only_even_for_s() -> None:
    search = LocalRoughCutSearch.__new__(LocalRoughCutSearch)
    search._catalog = _FakeCatalog(("title_card", "v", 0.2, 1))
    hit = _hit_with_ocr(["累计用户突破200万"])
    ctx = {"director_importance": "S", "s_keywords": ["200万", "用户"],
           "allow_tail_text": True, "needed_duration_ms": 2000}
    kept = search._filter_non_editable([hit], ctx)
    assert len(kept) == 1
    assert kept[0].schedule_level == "c_tail"


def test_ocr_s_requires_matching_keyword() -> None:
    search = LocalRoughCutSearch.__new__(LocalRoughCutSearch)
    search._catalog = _FakeCatalog(("title_card", "v", 0.2, 3))
    hit = _hit_with_ocr(["无关字幕"])
    ctx = {"director_importance": "S", "s_keywords": ["200万"]}
    assert search._filter_non_editable([hit], ctx) == []


def test_matching_title_card_is_not_allowed_at_start_or_for_a_long_window() -> None:
    search = LocalRoughCutSearch.__new__(LocalRoughCutSearch)
    search._catalog = _FakeCatalog(("title_card", "v", 0.2, 1))
    hit = _hit_with_ocr(["累计用户突破200万"])
    base = {"director_importance": "S", "s_keywords": ["200万", "用户"]}
    assert search._filter_non_editable([hit.model_copy(deep=True)], base) == []
    assert search._filter_non_editable([hit.model_copy(deep=True)], {
        **base, "allow_tail_text": True, "needed_duration_ms": 6000,
    }) == []


def test_generic_fallback_cannot_bypass_media_filter() -> None:
    search = LocalRoughCutSearch.__new__(LocalRoughCutSearch)
    search._catalog = _FakeCatalog(("technical_chart", "v", 0.2, 1))
    assert search._filter_non_editable([_hit(schedule_level="generic")]) == []


@pytest.mark.asyncio
async def test_neutral_candidates_recheck_generic_and_source_fallbacks() -> None:
    search = LocalRoughCutSearch.__new__(LocalRoughCutSearch)
    search._catalog = _FakeCatalog(("title_card", "v", 0.9, 6))

    async def generic(**kwargs):
        return [_hit(schedule_level="generic")]

    async def plain(**kwargs):
        return [_hit(schedule_level="source")]

    search._recall_generic_fallback = generic
    search._recall_plain_library_fallback = plain
    search._expand_to_semantic_spans = lambda hits, duration: hits
    assert await search.neutral_candidates(needed_duration_ms=4000) == []

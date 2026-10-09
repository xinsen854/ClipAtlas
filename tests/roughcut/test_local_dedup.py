"""Tests for the metadata-only local dedup post processor."""

from uuid import UUID, uuid4

from clipatlas.roughcut.local_dedup import LocalDedupPostProcessor
from clipatlas.roughcut.models import CandidateScore, RoughCutClip


def make_clip(
    *,
    video: UUID,
    source_in: int,
    source_out: int,
    timeline_in: int,
    timeline_out: int,
    reason: str = "检索命中",
) -> RoughCutClip:
    return RoughCutClip(
        beat_id=uuid4(),
        segment_id=uuid4(),
        video_id=video,
        source_uri=f"file:///E:/{video}.mp4",
        source_in_ms=source_in,
        source_out_ms=source_out,
        timeline_in_ms=timeline_in,
        timeline_out_ms=timeline_out,
        score=0.5,
        score_breakdown=CandidateScore(
            segment_id=uuid4(),
            semantic_score=0.5,
            action_score=0.5,
            scene_score=0.5,
            emotion_score=0.5,
            duration_fit_score=0.5,
            quality_score=0.5,
            continuity_bonus=0.0,
            reuse_penalty=0.0,
            total_score=0.5,
        ),
        selection_reason=reason,
        schedule_level="exact",
    )


VIDEO_A = uuid4()
VIDEO_B = uuid4()
DURATIONS = {VIDEO_A: 120_000, VIDEO_B: 60_000}


def test_merges_adjacent_same_source_nearby_clips() -> None:
    first = make_clip(video=VIDEO_A, source_in=10_000, source_out=14_000, timeline_in=0, timeline_out=4_000)
    second = make_clip(video=VIDEO_A, source_in=20_000, source_out=24_000, timeline_in=4_000, timeline_out=8_000)
    out = LocalDedupPostProcessor().process([first, second], DURATIONS)
    assert len(out) == 1
    assert out[0].source_out_ms == 18_000  # 14000 + second duration 4000
    assert out[0].timeline_out_ms == 8_000  # total preserved
    assert "本地去重" in out[0].selection_reason


def test_keeps_distant_same_source_clips() -> None:
    first = make_clip(video=VIDEO_A, source_in=10_000, source_out=14_000, timeline_in=0, timeline_out=4_000)
    second = make_clip(video=VIDEO_A, source_in=80_000, source_out=84_000, timeline_in=4_000, timeline_out=8_000)
    out = LocalDedupPostProcessor().process([first, second], DURATIONS)
    assert len(out) == 2


def test_keeps_different_sources_adjacent() -> None:
    first = make_clip(video=VIDEO_A, source_in=10_000, source_out=14_000, timeline_in=0, timeline_out=4_000)
    second = make_clip(video=VIDEO_B, source_in=20_000, source_out=24_000, timeline_in=4_000, timeline_out=8_000)
    out = LocalDedupPostProcessor().process([first, second], DURATIONS)
    assert len(out) == 2


def test_short_shot_merges_into_previous() -> None:
    first = make_clip(video=VIDEO_A, source_in=10_000, source_out=14_000, timeline_in=0, timeline_out=4_000)
    short = make_clip(video=VIDEO_A, source_in=15_000, source_out=18_500, timeline_in=4_000, timeline_out=7_500)
    third = make_clip(video=VIDEO_B, source_in=30_000, source_out=34_000, timeline_in=7_500, timeline_out=11_500)
    out = LocalDedupPostProcessor().process([first, short, third], DURATIONS)
    assert len(out) == 2
    # same-source gap of 1000ms triggers rule A: short absorbed, source extends forward
    assert out[0].source_out_ms == 17_500  # 14000 + 3500
    assert out[0].timeline_out_ms == 7_500
    assert out[1].timeline_in_ms == 7_500


def test_short_shot_merges_into_next_when_previous_is_other_source() -> None:
    first = make_clip(video=VIDEO_B, source_in=10_000, source_out=14_000, timeline_in=0, timeline_out=4_000)
    short = make_clip(video=VIDEO_A, source_in=20_000, source_out=23_700, timeline_in=4_000, timeline_out=7_700)
    third = make_clip(video=VIDEO_A, source_in=50_000, source_out=54_000, timeline_in=7_700, timeline_out=11_700)
    out = LocalDedupPostProcessor().process([first, short, third], DURATIONS)
    assert len(out) == 2
    # previous is a different source and the next same-source clip is far away,
    # so rule B absorbs the short shot into the next clip: source window shifts earlier
    assert out[1].source_in_ms == 46_300  # 50000 - 3700
    assert out[1].timeline_out_ms == 11_700
    assert out[1].timeline_in_ms == 4_000


def test_respects_material_duration_cap() -> None:
    first = make_clip(video=VIDEO_A, source_in=110_000, source_out=118_000, timeline_in=0, timeline_out=8_000)
    second = make_clip(video=VIDEO_A, source_in=119_000, source_out=123_000, timeline_in=8_000, timeline_out=12_000)
    # first.source_out + second duration = 122000 > 120000 cap => keep both
    out = LocalDedupPostProcessor().process([first, second], DURATIONS)
    assert len(out) == 2


def test_does_not_merge_reordered_same_source_windows() -> None:
    # curr source window starts BEFORE prev ends (source time jumps back):
    # not a continuous content family, must not merge (would skip material).
    first = make_clip(video=VIDEO_A, source_in=50_000, source_out=54_000, timeline_in=0, timeline_out=4_000)
    second = make_clip(video=VIDEO_A, source_in=10_000, source_out=14_000, timeline_in=4_000, timeline_out=8_000)
    out = LocalDedupPostProcessor().process([first, second], DURATIONS)
    assert len(out) == 2


def test_merges_ocr_similar_screens_across_different_sources() -> None:
    first = make_clip(video=VIDEO_A, source_in=10_000, source_out=14_000, timeline_in=0, timeline_out=4_000)
    second = make_clip(video=VIDEO_B, source_in=20_000, source_out=24_000, timeline_in=4_000, timeline_out=8_000)
    texts = {
        (VIDEO_A, 10_000, 14_000): "北京越野的产品谱系 正是一部不断自我超越的进化史",
        (VIDEO_B, 20_000, 24_000): "北京越野的产品谱系 正是一部不断自我超越的进化史 底气",
    }

    def ocr(video, start, end):
        return texts.get((video, start, end), "")

    out = LocalDedupPostProcessor(ocr_text=ocr).process([first, second], DURATIONS)
    assert len(out) == 1
    assert out[0].source_out_ms == 18_000  # first extended by second duration
    assert "同屏" in out[0].selection_reason


def test_keeps_ocr_different_screens() -> None:
    first = make_clip(video=VIDEO_A, source_in=10_000, source_out=14_000, timeline_in=0, timeline_out=4_000)
    second = make_clip(video=VIDEO_B, source_in=20_000, source_out=24_000, timeline_in=4_000, timeline_out=8_000)
    texts = {
        (VIDEO_A, 10_000, 14_000): "北京越野的产品谱系 进化史",
        (VIDEO_B, 20_000, 24_000): "医疗级双模制氧系统 7L/min 四人供氧",
    }

    def ocr(video, start, end):
        return texts.get((video, start, end), "")

    out = LocalDedupPostProcessor(ocr_text=ocr).process([first, second], DURATIONS)
    assert len(out) == 2


def test_total_duration_preserved_under_mixed_merges() -> None:
    clips = [
        make_clip(video=VIDEO_A, source_in=10_000, source_out=14_000, timeline_in=0, timeline_out=4_000),
        make_clip(video=VIDEO_A, source_in=16_000, source_out=20_000, timeline_in=4_000, timeline_out=8_000),
        make_clip(video=VIDEO_A, source_in=50_000, source_out=53_700, timeline_in=8_000, timeline_out=11_700),
        make_clip(video=VIDEO_B, source_in=5_000, source_out=9_000, timeline_in=11_700, timeline_out=15_700),
    ]
    before = sum(c.timeline_out_ms - c.timeline_in_ms for c in clips)
    out = LocalDedupPostProcessor().process(clips, DURATIONS)
    after = sum(c.timeline_out_ms - c.timeline_in_ms for c in out)
    assert after == before
    assert len(out) < len(clips)
    timeline = 0
    for clip in out:
        assert clip.timeline_in_ms == timeline
        timeline = clip.timeline_out_ms
    assert timeline == before

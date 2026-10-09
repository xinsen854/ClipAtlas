from uuid import uuid4

import pytest

from clipatlas.domain.models import SemanticAnnotation
from clipatlas.retrieval.search import SemanticSearchHit
from clipatlas.roughcut.beats import BeatBuilder
from clipatlas.roughcut.errors import RoughCutRetrievalError
from clipatlas.roughcut.models import ScriptBeat
from clipatlas.roughcut.pacing import (
    MAX_SHOT_MS,
    MIN_SHOT_MS,
    allocate_durations,
    has_pacing_capacity,
    review_windows,
)
from clipatlas.roughcut.planner import RoughCutPlanner
from clipatlas.roughcut.scoring import CandidateScorer
from clipatlas.speech.models import NarrationTrack, NarrationUnit


def hit(duration, score=0.9):
    segment_id = uuid4()
    return SemanticSearchHit(segment_id=segment_id, video_id=uuid4(),
        source_uri="file:///fixture.mp4", source_start_ms=0, source_end_ms=duration,
        score=score, effective_description="连续动作", embedding_provider="fixture",
        embedding_model="fixture", embedding_dimensions=1,
        annotation=SemanticAnnotation(segment_id=segment_id, origin="ai", description="连续动作"))


def fill(total, hits):
    planner = RoughCutPlanner.__new__(RoughCutPlanner)
    planner._scorer = CandidateScorer()
    beat = ScriptBeat(project_id=uuid4(), narration_track_id=uuid4(), sequence=0,
        text="连续动作说明", query_text="连续动作", timeline_start_ms=0, timeline_end_ms=total,
        target_duration_ms=total)
    return planner._fill_beat(beat, hits, {}, None)[0]


def test_balance_does_not_leave_a_sub_minimum_remainder():
    clips = fill(5335, [hit(8000)])
    durations = [c.timeline_out_ms - c.timeline_in_ms for c in clips]
    assert durations == [5335]


def test_balance_splits_into_two_valid_shots():
    clips = fill(7000, [hit(5000), hit(5000)])
    durations = [c.timeline_out_ms - c.timeline_in_ms for c in clips]
    assert sorted(durations) == [3500, 3500]
    assert clips[0].timeline_out_ms == clips[1].timeline_in_ms


def test_long_relevant_shot_beats_many_tiny_higher_scoring_hits():
    long = hit(8000, 0.85)
    clips = fill(7000, [*[hit(1000, 0.99) for _ in range(8)], long])
    assert len(clips) == 1 and clips[0].segment_id == long.segment_id
    assert clips[0].source_out_ms == 7000


def test_s_sentence_uses_one_continuous_shot_beyond_normal_pacing_limit():
    planner = RoughCutPlanner.__new__(RoughCutPlanner)
    planner._scorer = CandidateScorer()
    unit = {
        "text_range": "核心卖点完整句。", "importance": "S", "topic": "核心卖点",
        "required_objects": ["车辆"], "required_actions": [],
        "required_subjects": [], "acceptable_surrogates": [], "avoid": [],
    }
    beat = ScriptBeat(
        project_id=uuid4(), narration_track_id=uuid4(), sequence=0,
        text="核心卖点完整句。", query_text="核心卖点完整句。",
        timeline_start_ms=0, timeline_end_ms=11_000, target_duration_ms=11_000,
        retrieval_intent={"director_importance": "S", "director_units": [unit]},
    )
    long = hit(12_000)
    long.annotation.objects = ["车辆"]

    clips = planner._fill_beat(beat, [long], {}, None)[0]

    assert len(clips) == 1
    assert clips[0].timeline_out_ms == 11_000


def test_shortage_uses_short_readable_ranges_instead_of_reporting_corruption():
    clips = fill(7000, [hit(1000) for _ in range(10)])
    assert clips[-1].timeline_out_ms == 7000
    assert all(c.timeline_out_ms > c.timeline_in_ms for c in clips)
    assert not has_pacing_capacity(4800, [4000, 4000])
    assert has_pacing_capacity(4800, [4000, 5000])


def test_variable_capacities_balance_and_preserve_every_millisecond():
    durations = allocate_durations(13001, [5000, 8000, 3000])
    assert durations is not None and sum(durations) == 13001
    assert all(MIN_SHOT_MS <= d <= MAX_SHOT_MS for d in durations)
    assert all(d <= cap for d, cap in zip(durations, [5000, 8000, 3000], strict=True))
    assert review_windows(10000, 26335, MIN_SHOT_MS) == [(10000, 15445), (15445, 20890), (20890, 26335)]


def test_true_short_content_can_remain_one_shot_but_not_multiple_fragments():
    assert len(fill(1200, [hit(3000)])) == 1
    clips = fill(1200, [hit(400), hit(800)])
    assert clips[-1].timeline_out_ms == 1200
    assert all(c.timeline_out_ms > c.timeline_in_ms for c in clips)


def test_comma_continuation_can_share_one_content_window_without_changing_audio_times():
    track = NarrationTrack(project_id=uuid4(), source_mode="tts", duration_ms=7000,
                           script_hash="fixture", timing_quality="unit_exact")
    units = [NarrationUnit(track_id=track.id, sequence=i, text=text, text_hash=str(i),
                           start_ms=start, end_ms=end)
             for i, (text, start, end) in enumerate([
                 ("拿起咖啡杯，", 0, 2000), ("杯中冒着热气。", 2000, 5000), ("走向门外。", 5000, 7000)])]
    before = [u.model_dump() for u in units]
    beats = BeatBuilder().build(track, units)
    assert [b.target_duration_ms for b in beats] == [5000, 2000]
    assert beats[0].text == "拿起咖啡杯， 杯中冒着热气。"
    assert [u.model_dump() for u in units] == before

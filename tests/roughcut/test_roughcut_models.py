from uuid import uuid4

import pytest
from pydantic import ValidationError

from clipatlas.roughcut.models import (
    CandidateScore,
    PlannerSettings,
    RoughCutClip,
    ScriptBeat,
)


def _score() -> CandidateScore:
    return CandidateScore(
        segment_id=uuid4(),
        semantic_score=0.8,
        action_score=0.0,
        scene_score=0.0,
        emotion_score=0.0,
        duration_fit_score=0.8,
        quality_score=0.5,
        continuity_bonus=0.0,
        reuse_penalty=0.0,
        total_score=0.6,
    )


def test_script_beat_duration_must_match_timeline_window() -> None:
    with pytest.raises(ValidationError):
        ScriptBeat(
            project_id=uuid4(),
            narration_track_id=uuid4(),
            sequence=0,
            text="她推开仓库门",
            timeline_start_ms=100,
            timeline_end_ms=1100,
            target_duration_ms=900,
            query_text="她推开仓库门",
        )


def test_script_beat_requires_positive_ordered_window() -> None:
    with pytest.raises(ValidationError):
        ScriptBeat(
            project_id=uuid4(),
            narration_track_id=uuid4(),
            sequence=0,
            text="测试",
            timeline_start_ms=1000,
            timeline_end_ms=1000,
            target_duration_ms=1,
            query_text="测试",
        )


def test_rough_cut_clip_requires_equal_source_and_timeline_duration() -> None:
    with pytest.raises(ValidationError):
        RoughCutClip(
            beat_id=uuid4(),
            segment_id=uuid4(),
            video_id=uuid4(),
            source_uri="file:///a.mp4",
            source_in_ms=100,
            source_out_ms=900,
            timeline_in_ms=0,
            timeline_out_ms=1000,
            score=0.8,
            score_breakdown=_score(),
            selection_reason="test",
        )


def test_rough_cut_clip_requires_positive_source_window() -> None:
    with pytest.raises(ValidationError):
        RoughCutClip(
            beat_id=uuid4(),
            segment_id=uuid4(),
            video_id=uuid4(),
            source_uri="file:///a.mp4",
            source_in_ms=100,
            source_out_ms=100,
            timeline_in_ms=0,
            timeline_out_ms=1,
            score=0.8,
            score_breakdown=_score(),
            selection_reason="test",
        )


def test_default_settings_lock_v01_weights() -> None:
    settings = PlannerSettings()

    assert settings.top_k == 12
    assert settings.semantic_weight == 0.58
    assert settings.action_weight == 0.08
    assert settings.scene_weight == 0.08
    assert settings.emotion_weight == 0.06
    assert settings.duration_weight == 0.12
    assert settings.quality_weight == 0.05
    assert settings.max_continuity_bonus == 0.03
    assert settings.reuse_penalty_per_use == 0.08
    assert settings.max_reuse_penalty == 0.20


def test_settings_reject_top_k_outside_supported_range() -> None:
    with pytest.raises(ValidationError):
        PlannerSettings(top_k=0)
    with pytest.raises(ValidationError):
        PlannerSettings(top_k=101)


def test_candidate_score_rejects_positive_component_outside_unit_interval() -> None:
    with pytest.raises(ValidationError):
        CandidateScore(
            segment_id=uuid4(),
            semantic_score=1.1,
            action_score=0.0,
            scene_score=0.0,
            emotion_score=0.0,
            duration_fit_score=1.0,
            quality_score=0.5,
            continuity_bonus=0.0,
            reuse_penalty=0.0,
            total_score=0.6,
        )

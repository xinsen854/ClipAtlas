from uuid import uuid4

from clipatlas.integrations.finecut.roughcut_bridge import timeline_from_roughcut
from clipatlas.roughcut.models import (
    CandidateScore,
    PlannerSettings,
    RoughCutClip,
    RoughCutPlan,
    ScriptBeat,
)


def make_plan() -> RoughCutPlan:
    project_id = uuid4()
    narration_track_id = uuid4()
    beat = ScriptBeat(
        project_id=project_id,
        narration_track_id=narration_track_id,
        sequence=0,
        text="测试旁白",
        timeline_start_ms=1_000,
        timeline_end_ms=3_000,
        target_duration_ms=2_000,
        query_text="测试旁白",
    )
    score = CandidateScore(
        segment_id=uuid4(),
        semantic_score=0.9,
        action_score=0.8,
        scene_score=0.7,
        emotion_score=0.6,
        duration_fit_score=1.0,
        quality_score=0.9,
        continuity_bonus=0.0,
        reuse_penalty=0.0,
        total_score=0.85,
    )
    clip = RoughCutClip(
        beat_id=beat.id,
        segment_id=score.segment_id,
        video_id=uuid4(),
        source_uri="D:/media/source.mp4",
        source_in_ms=5_000,
        source_out_ms=7_000,
        timeline_in_ms=1_000,
        timeline_out_ms=3_000,
        score=0.85,
        score_breakdown=score,
        selection_reason="existing rough-cut selection",
    )
    return RoughCutPlan(
        project_id=project_id,
        narration_track_id=narration_track_id,
        narration_revision=1,
        revision=1,
        total_duration_ms=4_000,
        settings=PlannerSettings(),
        beats=[beat],
        clips=[clip],
    )


def test_timeline_from_roughcut_preserves_source_and_timeline_ranges() -> None:
    plan = make_plan()

    document = timeline_from_roughcut(plan)

    assert document.project_id == plan.project_id
    assert document.source_plan_id == plan.id
    assert len(document.tracks) == 1
    assert document.tracks[0].kind == "video"
    timeline_clip = document.tracks[0].clips[0]
    roughcut_clip = plan.clips[0]
    assert timeline_clip.source_id == str(roughcut_clip.segment_id)
    assert timeline_clip.source_path == roughcut_clip.source_uri
    assert timeline_clip.source_in_ms == roughcut_clip.source_in_ms
    assert timeline_clip.source_out_ms == roughcut_clip.source_out_ms
    assert timeline_clip.timeline_start_ms == roughcut_clip.timeline_in_ms
    assert timeline_clip.duration_ms == roughcut_clip.timeline_out_ms - roughcut_clip.timeline_in_ms


def test_timeline_from_roughcut_does_not_mutate_plan() -> None:
    plan = make_plan()
    before = plan.model_dump(mode="json")

    timeline_from_roughcut(plan, width=1280, height=720, fps=25.0)

    assert plan.model_dump(mode="json") == before

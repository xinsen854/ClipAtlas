from pathlib import Path
from uuid import uuid4

import opentimelineio as otio
import pytest

from clipatlas.exports.errors import (
    ExportInvariantError,
    ExportNotReadyError,
    OtioSerializationError,
)
from clipatlas.exports.otio import OtioTimelineBuilder
from clipatlas.roughcut.models import (
    CandidateScore,
    PlannerSettings,
    RoughCutClip,
    RoughCutPlan,
    ScriptBeat,
)
from clipatlas.speech.models import NarrationSourceMode, NarrationTrack, TimingQuality


def _score(segment_id):
    return CandidateScore(
        segment_id=segment_id,
        semantic_score=0.9,
        action_score=0.8,
        scene_score=0.7,
        emotion_score=0.6,
        duration_fit_score=1.0,
        quality_score=0.9,
        continuity_bonus=0.03,
        reuse_penalty=0.0,
        total_score=0.86,
    )


def _plan(*, total_duration_ms: int = 3000) -> RoughCutPlan:
    project_id = uuid4()
    narration_track_id = uuid4()
    beat_id = uuid4()
    first_segment_id = uuid4()
    second_segment_id = uuid4()
    beat = ScriptBeat(
        id=beat_id,
        project_id=project_id,
        narration_track_id=narration_track_id,
        sequence=0,
        text="雨夜里的男人走进便利店。",
        timeline_start_ms=0,
        timeline_end_ms=total_duration_ms,
        target_duration_ms=total_duration_ms,
        query_text="雨夜 男人 便利店",
    )
    clips = [
        RoughCutClip(
            beat_id=beat_id,
            segment_id=first_segment_id,
            video_id=uuid4(),
            source_uri=Path("/tmp/source-a.mp4").resolve().as_uri(),
            source_in_ms=83_420,
            source_out_ms=84_670,
            timeline_in_ms=0,
            timeline_out_ms=1250,
            score=0.86,
            score_breakdown=_score(first_segment_id),
            selection_reason="best semantic and duration fit",
        ),
        RoughCutClip(
            beat_id=beat_id,
            segment_id=second_segment_id,
            video_id=uuid4(),
            source_uri=Path("/tmp/source-b.mp4").resolve().as_uri(),
            source_in_ms=12_000,
            source_out_ms=13_750,
            timeline_in_ms=1250,
            timeline_out_ms=3000,
            score=0.81,
            score_breakdown=_score(second_segment_id),
            selection_reason="fills remaining narration window",
        ),
    ]
    return RoughCutPlan(
        project_id=project_id,
        narration_track_id=narration_track_id,
        narration_revision=2,
        revision=3,
        total_duration_ms=total_duration_ms,
        settings=PlannerSettings(),
        beats=[beat],
        clips=clips,
    )


def _narration(plan: RoughCutPlan, *, audio_uri: str | None = None) -> NarrationTrack:
    return NarrationTrack(
        id=plan.narration_track_id,
        project_id=plan.project_id,
        source_mode=NarrationSourceMode.TTS,
        script_hash="script-v2",
        provider="fake",
        model="fake-tts",
        audio_uri=audio_uri or Path("/tmp/narration.wav").resolve().as_uri(),
        duration_ms=plan.total_duration_ms,
        timing_quality=TimingQuality.UNIT_EXACT,
        revision=plan.narration_revision,
    )


def test_build_preserves_exact_millisecond_timing_and_metadata() -> None:
    plan = _plan()
    narration = _narration(plan)

    timeline = OtioTimelineBuilder().build(plan, narration)

    video_tracks = timeline.video_tracks()
    audio_tracks = timeline.audio_tracks()
    assert len(video_tracks) == 1
    assert len(audio_tracks) == 1

    first = video_tracks[0][0]
    assert first.source_range.start_time.value == 83_420
    assert first.source_range.start_time.rate == 1000
    assert first.source_range.duration.value == 1250
    assert first.source_range.duration.rate == 1000
    assert first.media_reference.target_url == plan.clips[0].source_uri
    assert first.metadata["clipatlas"]["timeline_in_ms"] == 0
    assert first.metadata["clipatlas"]["timeline_out_ms"] == 1250
    assert first.metadata["clipatlas"]["segment_id"] == str(plan.clips[0].segment_id)

    narration_clip = audio_tracks[0][0]
    assert narration_clip.source_range.start_time.value == 0
    assert narration_clip.source_range.start_time.rate == 1000
    assert narration_clip.source_range.duration.value == 3000
    assert narration_clip.source_range.duration.rate == 1000
    assert narration_clip.media_reference.target_url == narration.audio_uri

    assert timeline.duration().value == 3000
    assert timeline.duration().rate == 1000
    metadata = timeline.metadata["clipatlas"]
    assert metadata["plan_id"] == str(plan.id)
    assert metadata["project_id"] == str(plan.project_id)
    assert metadata["narration_track_id"] == str(plan.narration_track_id)
    assert metadata["narration_revision"] == 2
    assert metadata["rough_cut_revision"] == 3
    assert metadata["total_duration_ms"] == 3000
    assert metadata["timing_rate"] == 1000


def test_build_rejects_empty_plan() -> None:
    plan = _plan()
    plan = plan.model_copy(update={"clips": []})

    with pytest.raises(ExportInvariantError, match="at least one clip"):
        OtioTimelineBuilder().build(plan, _narration(plan))


def test_build_rejects_nonzero_timeline_start() -> None:
    plan = _plan()
    first = plan.clips[0].model_copy(update={"timeline_in_ms": 1, "timeline_out_ms": 1251})
    plan = plan.model_copy(update={"clips": [first, plan.clips[1]]})

    with pytest.raises(ExportInvariantError, match="start at 0"):
        OtioTimelineBuilder().build(plan, _narration(plan))


def test_build_rejects_timeline_gap() -> None:
    plan = _plan()
    second = plan.clips[1].model_copy(update={"timeline_in_ms": 1300, "timeline_out_ms": 3050})
    plan = plan.model_copy(update={"clips": [plan.clips[0], second]})

    with pytest.raises(ExportInvariantError, match="contiguous"):
        OtioTimelineBuilder().build(plan, _narration(plan))


def test_build_rejects_timeline_not_ending_at_total_duration() -> None:
    plan = _plan()
    second = plan.clips[1].model_copy(
        update={"source_out_ms": 13_700, "timeline_out_ms": 2950}
    )
    plan = plan.model_copy(update={"clips": [plan.clips[0], second]})

    with pytest.raises(ExportInvariantError, match="total duration"):
        OtioTimelineBuilder().build(plan, _narration(plan))


def test_build_rejects_source_destination_duration_mismatch() -> None:
    plan = _plan()
    first = plan.clips[0].model_copy(update={"source_out_ms": 84_600})
    plan = plan.model_copy(update={"clips": [first, plan.clips[1]]})

    with pytest.raises(ExportInvariantError, match="source and timeline durations"):
        OtioTimelineBuilder().build(plan, _narration(plan))


def test_build_rejects_empty_source_uri() -> None:
    plan = _plan()
    first = plan.clips[0].model_copy(update={"source_uri": ""})
    plan = plan.model_copy(update={"clips": [first, plan.clips[1]]})

    with pytest.raises(ExportInvariantError, match="source URI"):
        OtioTimelineBuilder().build(plan, _narration(plan))


def test_build_rejects_narration_from_another_project() -> None:
    plan = _plan()
    narration = _narration(plan).model_copy(update={"project_id": uuid4()})

    with pytest.raises(ExportNotReadyError, match="project"):
        OtioTimelineBuilder().build(plan, narration)


def test_build_rejects_missing_narration_audio() -> None:
    plan = _plan()
    narration = _narration(plan).model_copy(update={"audio_uri": None})

    with pytest.raises(ExportNotReadyError, match="audio"):
        OtioTimelineBuilder().build(plan, narration)


def test_build_rejects_narration_duration_mismatch() -> None:
    plan = _plan()
    narration = _narration(plan).model_copy(update={"duration_ms": 2999})

    with pytest.raises(ExportNotReadyError, match="duration"):
        OtioTimelineBuilder().build(plan, narration)


def test_write_verified_roundtrips_native_otio(tmp_path: Path) -> None:
    plan = _plan()
    builder = OtioTimelineBuilder()
    timeline = builder.build(plan, _narration(plan))
    output_path = tmp_path / "nested" / "roughcut-r3.otio"

    artifact = builder.write_verified(
        timeline,
        output_path,
        plan_id=plan.id,
        project_id=plan.project_id,
        narration_track_id=plan.narration_track_id,
    )

    assert artifact.output_path == output_path.resolve()
    assert artifact.plan_id == plan.id
    assert artifact.project_id == plan.project_id
    assert artifact.narration_track_id == plan.narration_track_id
    assert artifact.total_duration_ms == 3000
    assert artifact.timing_rate == 1000
    assert artifact.rough_cut_revision == 3
    assert artifact.narration_revision == 2
    assert output_path.is_file()

    roundtrip = otio.adapters.read_from_file(str(output_path))
    assert roundtrip.metadata["clipatlas"]["plan_id"] == str(plan.id)
    assert roundtrip.duration().value == 3000
    assert roundtrip.duration().rate == 1000
    first = roundtrip.video_tracks()[0][0]
    assert first.source_range.start_time.value == 83_420
    assert first.source_range.duration.value == 1250
    narration_clip = roundtrip.audio_tracks()[0][0]
    assert narration_clip.source_range.duration.value == 3000


def test_write_verified_normalizes_adapter_write_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan()
    builder = OtioTimelineBuilder()
    timeline = builder.build(plan, _narration(plan))

    def fail_write(*args, **kwargs):
        raise RuntimeError("adapter write failed")

    monkeypatch.setattr(otio.adapters, "write_to_file", fail_write)

    with pytest.raises(OtioSerializationError, match="write"):
        builder.write_verified(
            timeline,
            tmp_path / "broken.otio",
            plan_id=plan.id,
            project_id=plan.project_id,
            narration_track_id=plan.narration_track_id,
        )


def test_write_verified_normalizes_readback_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan()
    builder = OtioTimelineBuilder()
    timeline = builder.build(plan, _narration(plan))

    def fail_read(*args, **kwargs):
        raise RuntimeError("adapter read failed")

    monkeypatch.setattr(otio.adapters, "read_from_file", fail_read)

    with pytest.raises(OtioSerializationError, match="verify"):
        builder.write_verified(
            timeline,
            tmp_path / "broken-read.otio",
            plan_id=plan.id,
            project_id=plan.project_id,
            narration_track_id=plan.narration_track_id,
        )

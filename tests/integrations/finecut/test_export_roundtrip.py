from pathlib import Path
from uuid import uuid4

import opentimelineio as otio

from clipatlas.integrations.finecut.export_roundtrip import FineCutOtioBuilder
from clipatlas.roughcut.models import PlannerSettings, RoughCutPlan
from clipatlas.speech.models import NarrationSourceMode, NarrationTrack, TimingQuality
from finecut.models import Clip, TimelineDocument, Track


def _narration(project_id, *, duration_ms: int = 5000) -> NarrationTrack:
    return NarrationTrack(
        project_id=project_id,
        source_mode=NarrationSourceMode.TTS,
        script_hash="phase-7a",
        provider="fake",
        model="fake",
        audio_uri=(Path("/tmp") / "narration.wav").resolve().as_uri(),
        duration_ms=duration_ms,
        timing_quality=TimingQuality.UNIT_EXACT,
        revision=3,
    )


def _document(tmp_path: Path) -> tuple[TimelineDocument, RoughCutPlan, NarrationTrack]:
    project_id = uuid4()
    narration = _narration(project_id)
    plan = RoughCutPlan(
        project_id=project_id,
        narration_track_id=narration.id,
        narration_revision=narration.revision,
        revision=4,
        total_duration_ms=5000,
        settings=PlannerSettings(),
        beats=[],
        clips=[],
    )
    media_a = tmp_path / "a.mp4"
    media_b = tmp_path / "b.mp4"
    media_a.touch()
    media_b.touch()
    track = Track(
        kind="video",
        clips=[
            Clip(
                source_id="library-media-a",
                source_path=media_a.resolve().as_uri(),
                timeline_start_ms=0,
                duration_ms=1500,
                source_in_ms=700,
                source_out_ms=2200,
                opacity=0.65,
                volume=0.4,
                transform={
                    "position_x": 12.0,
                    "position_y": -7.0,
                    "scale": 1.15,
                    "rotation": 3.0,
                },
                effects=[{"type": "existing", "params": {"amount": 0.2}}],
            ),
            Clip(
                source_id="library-media-b",
                source_path=str(media_b.resolve()),
                timeline_start_ms=2500,
                duration_ms=1000,
                source_in_ms=5000,
                source_out_ms=6000,
                opacity=1.0,
                volume=1.0,
            ),
        ],
    )
    document = TimelineDocument(
        version=1,
        project_id=project_id,
        source_plan_id=plan.id,
        width=1080,
        height=1920,
        fps=30,
        duration_ms=4000,
        tracks=[track],
    )
    return document, plan, narration


def test_finecut_otio_projects_final_document_without_mutating_it(tmp_path: Path) -> None:
    document, plan, narration = _document(tmp_path)
    before = document.model_dump(mode="json")

    timeline = FineCutOtioBuilder().build(document, plan, narration)

    assert document.model_dump(mode="json") == before
    metadata = timeline.metadata["clipatlas"]
    assert metadata["plan_id"] == str(plan.id)
    assert metadata["project_id"] == str(document.project_id)
    assert metadata["narration_track_id"] == str(narration.id)
    assert metadata["finecut"]["version"] == 1
    assert metadata["finecut"]["document_version"] == document.version
    assert metadata["finecut"]["width"] == 1080
    assert metadata["finecut"]["height"] == 1920
    assert metadata["finecut"]["fps"] == 30
    assert metadata["finecut"]["duration_ms"] == 4000
    assert metadata["finecut"]["video_track_id"] == str(document.tracks[0].id)

    video = timeline.video_tracks()[0]
    assert len(video) == 4  # clip, gap, clip, trailing gap
    assert isinstance(video[1], otio.schema.Gap)
    assert isinstance(video[3], otio.schema.Gap)
    assert video[1].duration().value == 1000
    assert video[3].duration().value == 500

    first = video[0]
    assert first.source_range.start_time.value == 700
    assert first.source_range.duration.value == 1500
    clipatlas = first.metadata["clipatlas"]
    finecut = clipatlas["finecut"]
    assert finecut["version"] == 1
    assert finecut["clip_id"] == str(document.tracks[0].clips[0].id)
    assert finecut["source_id"] == "library-media-a"
    assert finecut["opacity"] == 0.65
    assert finecut["volume"] == 0.4
    transform = finecut["transform"]
    assert dict(transform) == {
        "position_x": 12.0,
        "position_y": -7.0,
        "scale": 1.15,
        "rotation": 3.0,
    }
    effects = finecut["effects"]
    assert len(effects) == 1
    effect = effects[0]
    assert effect["type"] == "existing"
    params = effect["params"]
    assert dict(params) == {"amount": 0.2}


def test_finecut_otio_keeps_narration_separate_when_durations_differ(tmp_path: Path) -> None:
    document, plan, narration = _document(tmp_path)
    timeline = FineCutOtioBuilder().build(document, plan, narration)

    assert timeline.video_tracks()[0].duration().value == document.duration_ms
    assert timeline.audio_tracks()[0].duration().value == narration.duration_ms
    assert timeline.duration().value == max(document.duration_ms, narration.duration_ms)
    assert timeline.metadata["clipatlas"]["total_duration_ms"] == 5000
    assert timeline.metadata["clipatlas"]["finecut"]["duration_ms"] == 4000

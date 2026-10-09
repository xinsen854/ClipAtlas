from pathlib import Path
from uuid import UUID, uuid4

import opentimelineio as otio
import pytest

from clipatlas.exports.errors import ExportNotReadyError, TimelineExportError
from clipatlas.exports.models import JianyingDraftArtifact, JianyingExportSettings
from clipatlas.exports.service import TimelineExportService
from clipatlas.roughcut.models import (
    CandidateScore,
    PlannerSettings,
    RoughCutClip,
    RoughCutPlan,
    ScriptBeat,
)
from clipatlas.roughcut.store import RoughCutStore
from clipatlas.speech.models import NarrationSourceMode, NarrationTrack, TimingQuality
from clipatlas.speech.store import NarrationStore


class _RecordingJianyingBackend:
    name = "recording"
    version = "1"

    def __init__(self) -> None:
        self.timeline: otio.schema.Timeline | None = None

    def export(
        self,
        timeline: otio.schema.Timeline,
        *,
        draft_name: str,
        settings: JianyingExportSettings,
    ) -> JianyingDraftArtifact:
        self.timeline = timeline
        metadata = timeline.metadata["clipatlas"]
        return JianyingDraftArtifact(
            plan_id=UUID(metadata["plan_id"]),
            project_id=UUID(metadata["project_id"]),
            narration_track_id=UUID(metadata["narration_track_id"]),
            draft_name=draft_name,
            output_path=(settings.draft_root / draft_name).resolve(),
            mode=settings.mode,
            backend_name=self.name,
            backend_version=self.version,
            total_duration_ms=metadata["total_duration_ms"],
        )


def _score(segment_id: UUID) -> CandidateScore:
    return CandidateScore(
        segment_id=segment_id,
        semantic_score=0.9,
        action_score=0.8,
        scene_score=0.7,
        emotion_score=0.6,
        duration_fit_score=1.0,
        quality_score=0.9,
        continuity_bonus=0.0,
        reuse_penalty=0.0,
        total_score=0.84,
    )


def _track(project_id: UUID, revision: int, audio_name: str) -> NarrationTrack:
    return NarrationTrack(
        project_id=project_id,
        source_mode=NarrationSourceMode.TTS,
        script_hash=f"script-r{revision}",
        provider="fake",
        model="fake-tts",
        audio_uri=(Path("/tmp") / audio_name).resolve().as_uri(),
        duration_ms=3000,
        timing_quality=TimingQuality.UNIT_EXACT,
        revision=revision,
    )


def _plan(project_id: UUID, narration: NarrationTrack, *, revision: int = 1) -> RoughCutPlan:
    beat_id = uuid4()
    segment_id = uuid4()
    beat = ScriptBeat(
        id=beat_id,
        project_id=project_id,
        narration_track_id=narration.id,
        sequence=0,
        text="雨夜街头。",
        timeline_start_ms=0,
        timeline_end_ms=3000,
        target_duration_ms=3000,
        query_text="雨夜 街头",
    )
    clip = RoughCutClip(
        beat_id=beat_id,
        segment_id=segment_id,
        video_id=uuid4(),
        source_uri=Path("/tmp/source.mp4").resolve().as_uri(),
        source_in_ms=8000,
        source_out_ms=11_000,
        timeline_in_ms=0,
        timeline_out_ms=3000,
        score=0.84,
        score_breakdown=_score(segment_id),
        selection_reason="historical export fixture",
    )
    return RoughCutPlan(
        project_id=project_id,
        narration_track_id=narration.id,
        narration_revision=narration.revision,
        revision=revision,
        total_duration_ms=3000,
        settings=PlannerSettings(),
        beats=[beat],
        clips=[clip],
    )


def test_export_otio_resolves_historical_narration_not_current_active_track(
    tmp_path: Path,
) -> None:
    project_id = uuid4()
    narration_store = NarrationStore(tmp_path / "narration.sqlite3")
    rough_cut_store = RoughCutStore(tmp_path / "roughcut.sqlite3")
    revision_1 = _track(project_id, 1, "narration-r1.wav")
    revision_2 = _track(project_id, 2, "narration-r2.wav")
    narration_store.save_track(revision_1)
    narration_store.save_track(revision_2)
    assert narration_store.activate_track(project_id, revision_2.id)
    plan = _plan(project_id, revision_1, revision=4)
    rough_cut_store.save_plan(plan)

    before_plan = rough_cut_store.get_plan(plan.id)
    before_revision_1 = narration_store.get_track(revision_1.id)
    before_revision_2 = narration_store.get_track(revision_2.id)
    service = TimelineExportService(
        rough_cut_store=rough_cut_store,
        narration_store=narration_store,
        export_root=tmp_path / "exports",
    )

    artifact = service.export_otio(plan.id)

    expected_path = (
        tmp_path
        / "exports"
        / str(project_id)
        / str(plan.id)
        / "roughcut-r4.otio"
    ).resolve()
    assert artifact.output_path == expected_path
    assert expected_path.is_file()
    timeline = otio.adapters.read_from_file(str(expected_path))
    narration_clip = timeline.audio_tracks()[0][0]
    assert narration_clip.media_reference.target_url == revision_1.audio_uri
    assert timeline.metadata["clipatlas"]["narration_track_id"] == str(revision_1.id)

    active = narration_store.get_active_track(project_id)
    assert active is not None
    assert active.id == revision_2.id
    assert rough_cut_store.get_plan(plan.id) == before_plan
    assert narration_store.get_track(revision_1.id) == before_revision_1
    assert narration_store.get_track(revision_2.id) == before_revision_2


def test_export_jianying_passes_exact_persisted_plan_timeline_to_backend_without_mutation(
    tmp_path: Path,
) -> None:
    project_id = uuid4()
    narration_store = NarrationStore(tmp_path / "narration.sqlite3")
    rough_cut_store = RoughCutStore(tmp_path / "roughcut.sqlite3")
    revision_1 = _track(project_id, 1, "narration-r1.wav")
    revision_2 = _track(project_id, 2, "narration-r2.wav")
    narration_store.save_track(revision_1)
    narration_store.save_track(revision_2)
    assert narration_store.activate_track(project_id, revision_2.id)
    plan = _plan(project_id, revision_1, revision=4)
    rough_cut_store.save_plan(plan)
    before_plan = rough_cut_store.get_plan(plan.id)
    before_revision_1 = narration_store.get_track(revision_1.id)
    before_revision_2 = narration_store.get_track(revision_2.id)
    backend = _RecordingJianyingBackend()
    service = TimelineExportService(
        rough_cut_store=rough_cut_store,
        narration_store=narration_store,
        export_root=tmp_path / "exports",
        jianying_backend=backend,
    )
    settings = JianyingExportSettings(draft_root=tmp_path / "drafts")

    artifact = service.export_jianying(
        plan.id,
        draft_name="ClipAtlas Portable",
        settings=settings,
    )

    assert backend.timeline is not None
    narration_clip = backend.timeline.audio_tracks()[0][0]
    assert narration_clip.media_reference.target_url == revision_1.audio_uri
    assert artifact.plan_id == plan.id
    active = narration_store.get_active_track(project_id)
    assert active is not None
    assert active.id == revision_2.id
    assert rough_cut_store.get_plan(plan.id) == before_plan
    assert narration_store.get_track(revision_1.id) == before_revision_1
    assert narration_store.get_track(revision_2.id) == before_revision_2


def test_export_otio_missing_plan_uses_specific_not_found_error(tmp_path: Path) -> None:
    service = TimelineExportService(
        rough_cut_store=RoughCutStore(tmp_path / "roughcut.sqlite3"),
        narration_store=NarrationStore(tmp_path / "narration.sqlite3"),
        export_root=tmp_path / "exports",
    )

    with pytest.raises(TimelineExportError, match="rough cut plan") as exc_info:
        service.export_otio(uuid4())

    assert exc_info.type.__name__ == "ExportPlanNotFoundError"
    assert not (tmp_path / "exports").exists()


def test_export_otio_missing_referenced_narration_does_not_mutate_plan(
    tmp_path: Path,
) -> None:
    project_id = uuid4()
    narration_store = NarrationStore(tmp_path / "narration.sqlite3")
    rough_cut_store = RoughCutStore(tmp_path / "roughcut.sqlite3")
    missing_track = _track(project_id, 1, "missing.wav")
    plan = _plan(project_id, missing_track)
    rough_cut_store.save_plan(plan)
    before_plan = rough_cut_store.get_plan(plan.id)
    service = TimelineExportService(
        rough_cut_store=rough_cut_store,
        narration_store=narration_store,
        export_root=tmp_path / "exports",
    )

    with pytest.raises(ExportNotReadyError, match="narration"):
        service.export_otio(plan.id)

    assert rough_cut_store.get_plan(plan.id) == before_plan
    assert not (tmp_path / "exports").exists()

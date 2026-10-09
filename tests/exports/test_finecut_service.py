from pathlib import Path
from uuid import UUID, uuid4

import opentimelineio as otio

from clipatlas.exports.models import JianyingDraftArtifact, JianyingExportSettings
from clipatlas.exports.service import TimelineExportService
from clipatlas.roughcut.models import CandidateScore, PlannerSettings, RoughCutClip, RoughCutPlan, ScriptBeat
from clipatlas.roughcut.store import RoughCutStore
from clipatlas.speech.models import NarrationSourceMode, NarrationTrack, TimingQuality
from clipatlas.speech.store import NarrationStore
from finecut.models import Clip, TimelineDocument, Track
from finecut.store import TimelineStore


class _RecordingBackend:
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
        semantic_score=1,
        action_score=1,
        scene_score=1,
        emotion_score=1,
        duration_fit_score=1,
        quality_score=1,
        continuity_bonus=0,
        reuse_penalty=0,
        total_score=1,
    )


def _fixture(tmp_path: Path):
    project_id = uuid4()
    narration = NarrationTrack(
        project_id=project_id,
        source_mode=NarrationSourceMode.TTS,
        script_hash="phase-7a",
        provider="fake",
        model="fake",
        audio_uri=(tmp_path / "narration.wav").resolve().as_uri(),
        duration_ms=3000,
        timing_quality=TimingQuality.UNIT_EXACT,
        revision=1,
    )
    beat_id = uuid4()
    segment_id = uuid4()
    beat = ScriptBeat(
        id=beat_id,
        project_id=project_id,
        narration_track_id=narration.id,
        sequence=0,
        text="final timeline",
        timeline_start_ms=0,
        timeline_end_ms=3000,
        target_duration_ms=3000,
        query_text="final timeline",
    )
    rough_media = tmp_path / "rough.mp4"
    rough_media.touch()
    plan = RoughCutPlan(
        project_id=project_id,
        narration_track_id=narration.id,
        narration_revision=1,
        revision=2,
        total_duration_ms=3000,
        settings=PlannerSettings(),
        beats=[beat],
        clips=[
            RoughCutClip(
                beat_id=beat_id,
                segment_id=segment_id,
                video_id=uuid4(),
                source_uri=rough_media.resolve().as_uri(),
                source_in_ms=0,
                source_out_ms=3000,
                timeline_in_ms=0,
                timeline_out_ms=3000,
                score=1,
                score_breakdown=_score(segment_id),
                selection_reason="rough",
            )
        ],
    )
    final_media = tmp_path / "final.mp4"
    final_media.touch()
    document = TimelineDocument(
        project_id=project_id,
        source_plan_id=plan.id,
        width=1080,
        height=1920,
        fps=30,
        duration_ms=3000,
        tracks=[
            Track(
                kind="video",
                clips=[
                    Clip(
                        source_id="final-media",
                        source_path=str(final_media.resolve()),
                        timeline_start_ms=0,
                        duration_ms=3000,
                        source_in_ms=1000,
                        source_out_ms=4000,
                        opacity=0.7,
                        volume=0.6,
                        transform={"scale": 1.1},
                    )
                ],
            )
        ],
    )
    rough_store = RoughCutStore(tmp_path / "rough.sqlite3")
    narration_store = NarrationStore(tmp_path / "narration.sqlite3")
    finecut_store = TimelineStore(tmp_path / "finecut.sqlite3")
    rough_store.save_plan(plan)
    narration_store.save_track(narration)
    return plan, narration, document, rough_store, narration_store, finecut_store


def test_otio_export_prefers_saved_finecut_document(tmp_path: Path) -> None:
    plan, narration, document, rough_store, narration_store, finecut_store = _fixture(tmp_path)
    finecut_store.save(document)
    service = TimelineExportService(
        rough_cut_store=rough_store,
        narration_store=narration_store,
        finecut_timeline_store=finecut_store,
        export_root=tmp_path / "exports",
    )

    artifact = service.export_otio(plan.id)
    timeline = otio.adapters.read_from_file(str(artifact.output_path))

    assert artifact.output_path.name == "finecut.otio"
    assert timeline.video_tracks()[0][0].media_reference.target_url == str(
        (tmp_path / "final.mp4").resolve()
    )
    assert timeline.video_tracks()[0][0].source_range.start_time.value == 1000
    assert timeline.video_tracks()[0][0].metadata["clipatlas"]["finecut"]["opacity"] == 0.7
    assert timeline.metadata["clipatlas"]["narration_track_id"] == str(narration.id)


def test_otio_export_falls_back_to_roughcut_when_no_saved_finecut_exists(tmp_path: Path) -> None:
    plan, _, _, rough_store, narration_store, finecut_store = _fixture(tmp_path)
    service = TimelineExportService(
        rough_cut_store=rough_store,
        narration_store=narration_store,
        finecut_timeline_store=finecut_store,
        export_root=tmp_path / "exports",
    )

    artifact = service.export_otio(plan.id)
    timeline = otio.adapters.read_from_file(str(artifact.output_path))

    assert artifact.output_path.name == "roughcut-r2.otio"
    assert timeline.video_tracks()[0][0].media_reference.target_url == (
        tmp_path / "rough.mp4"
    ).resolve().as_uri()
    assert "finecut" not in timeline.metadata["clipatlas"]


def test_jianying_uses_same_final_finecut_otio_projection(tmp_path: Path) -> None:
    plan, _, document, rough_store, narration_store, finecut_store = _fixture(tmp_path)
    finecut_store.save(document)
    backend = _RecordingBackend()
    service = TimelineExportService(
        rough_cut_store=rough_store,
        narration_store=narration_store,
        finecut_timeline_store=finecut_store,
        export_root=tmp_path / "exports",
        jianying_backend=backend,
    )

    service.export_jianying(
        plan.id,
        draft_name="FineCut Final",
        settings=JianyingExportSettings(draft_root=tmp_path / "drafts"),
    )

    assert backend.timeline is not None
    clip = backend.timeline.video_tracks()[0][0]
    assert clip.media_reference.target_url == str((tmp_path / "final.mp4").resolve())
    assert clip.metadata["clipatlas"]["finecut"]["source_id"] == "final-media"

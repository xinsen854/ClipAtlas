import base64
import json
import wave
from pathlib import Path
from uuid import UUID, uuid4

import opentimelineio as otio
import pytest

from clipatlas.exports.errors import JianyingWriteError
from clipatlas.exports.jianying import PyJianYingDraftBackend
from clipatlas.exports.models import JianyingExportSettings
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


def _write_png(path: Path) -> None:
    path.write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFElEQVR4nGP8z8DAwMDAxMDAwAIAAwAB/5nQxQAAAABJRU5ErkJggg=="
        )
    )


def _write_silent_wav(path: Path, duration_ms: int) -> None:
    sample_rate = 8000
    frame_count = sample_rate * duration_ms // 1000
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * frame_count)


def _track(
    project_id: UUID,
    revision: int,
    audio_path: Path,
) -> NarrationTrack:
    return NarrationTrack(
        project_id=project_id,
        source_mode=NarrationSourceMode.TTS,
        script_hash=f"script-r{revision}",
        provider="integration-fixture",
        model="fixture-tts",
        audio_uri=audio_path.resolve().as_uri(),
        duration_ms=3000,
        timing_quality=TimingQuality.UNIT_EXACT,
        revision=revision,
    )


def _score(segment_id: UUID, total_score: float) -> CandidateScore:
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
        total_score=total_score,
    )


def _plan(
    project_id: UUID,
    narration: NarrationTrack,
    video_path: Path,
) -> RoughCutPlan:
    beat_1 = ScriptBeat(
        id=uuid4(),
        project_id=project_id,
        narration_track_id=narration.id,
        sequence=0,
        text="雨夜街头。",
        timeline_start_ms=0,
        timeline_end_ms=1000,
        target_duration_ms=1000,
        query_text="雨夜 街头",
    )
    beat_2 = ScriptBeat(
        id=uuid4(),
        project_id=project_id,
        narration_track_id=narration.id,
        sequence=1,
        text="人物继续前行。",
        timeline_start_ms=1000,
        timeline_end_ms=3000,
        target_duration_ms=2000,
        query_text="人物 行走",
    )
    segment_1 = uuid4()
    segment_2 = uuid4()
    source_uri = video_path.resolve().as_uri()
    clips = [
        RoughCutClip(
            beat_id=beat_1.id,
            segment_id=segment_1,
            video_id=uuid4(),
            source_uri=source_uri,
            source_in_ms=5000,
            source_out_ms=6000,
            timeline_in_ms=0,
            timeline_out_ms=1000,
            score=0.84,
            score_breakdown=_score(segment_1, 0.84),
            selection_reason="integration fixture 1",
        ),
        RoughCutClip(
            beat_id=beat_2.id,
            segment_id=segment_2,
            video_id=uuid4(),
            source_uri=source_uri,
            source_in_ms=9000,
            source_out_ms=11_000,
            timeline_in_ms=1000,
            timeline_out_ms=3000,
            score=0.82,
            score_breakdown=_score(segment_2, 0.82),
            selection_reason="integration fixture 2",
        ),
    ]
    return RoughCutPlan(
        project_id=project_id,
        narration_track_id=narration.id,
        narration_revision=narration.revision,
        revision=4,
        total_duration_ms=3000,
        settings=PlannerSettings(),
        beats=[beat_1, beat_2],
        clips=clips,
    )


class _FailingBackend:
    name = "failing-fixture"
    version = "1"

    def __init__(self) -> None:
        self.calls = 0

    def export(self, *args, **kwargs):
        del args, kwargs
        self.calls += 1
        raise JianyingWriteError("forced integration failure")


def test_persisted_historical_plan_exports_exact_otio_and_editable_jianying_draft(
    tmp_path: Path,
) -> None:
    video_path = tmp_path / "source.png"
    narration_r1_path = tmp_path / "narration-r1.wav"
    narration_r2_path = tmp_path / "narration-r2.wav"
    _write_png(video_path)
    _write_silent_wav(narration_r1_path, 3000)
    _write_silent_wav(narration_r2_path, 3000)

    project_id = uuid4()
    narration_store = NarrationStore(tmp_path / "narration.sqlite3")
    rough_cut_store = RoughCutStore(tmp_path / "roughcut.sqlite3")
    narration_r1 = _track(project_id, 1, narration_r1_path)
    narration_r2 = _track(project_id, 2, narration_r2_path)
    narration_store.save_track(narration_r1)
    narration_store.save_track(narration_r2)
    assert narration_store.activate_track(project_id, narration_r2.id)
    plan = _plan(project_id, narration_r1, video_path)
    rough_cut_store.save_plan(plan)

    service = TimelineExportService(
        rough_cut_store=rough_cut_store,
        narration_store=narration_store,
        export_root=tmp_path / "exports",
        jianying_backend=PyJianYingDraftBackend(),
    )

    otio_artifact = service.export_otio(plan.id)
    timeline = otio.adapters.read_from_file(str(otio_artifact.output_path))
    metadata = timeline.metadata["clipatlas"]
    assert metadata["plan_id"] == str(plan.id)
    assert metadata["project_id"] == str(project_id)
    assert metadata["narration_track_id"] == str(narration_r1.id)
    assert metadata["total_duration_ms"] == 3000
    assert timeline.duration().value == 3000
    assert timeline.duration().rate == 1000
    assert [
        (
            clip.source_range.start_time.value,
            clip.source_range.duration.value,
        )
        for clip in timeline.video_tracks()[0]
    ] == [(5000, 1000), (9000, 2000)]
    narration_clip = timeline.audio_tracks()[0][0]
    assert narration_clip.media_reference.target_url == narration_r1.audio_uri
    assert narration_clip.source_range.duration.value == 3000

    active = narration_store.get_active_track(project_id)
    assert active is not None
    assert active.id == narration_r2.id

    draft_settings = JianyingExportSettings(draft_root=tmp_path / "drafts")
    jianying_artifact = service.export_jianying(
        plan.id,
        draft_name="ClipAtlas E2E",
        settings=draft_settings,
    )
    draft_content_path = jianying_artifact.output_path / "draft_content.json"
    assert draft_content_path.is_file()
    draft_content = json.loads(draft_content_path.read_text(encoding="utf-8"))
    tracks = {track["name"]: track for track in draft_content["tracks"]}
    assert set(tracks) == {"main_video", "narration"}
    assert [segment["source_timerange"] for segment in tracks["main_video"]["segments"]] == [
        {"start": 5_000_000, "duration": 1_000_000},
        {"start": 9_000_000, "duration": 2_000_000},
    ]
    assert tracks["narration"]["segments"][0]["target_timerange"] == {
        "start": 0,
        "duration": 3_000_000,
    }


def test_jianying_failure_preserves_existing_otio_plan_narration_and_is_retryable(
    tmp_path: Path,
) -> None:
    video_path = tmp_path / "source.png"
    narration_path = tmp_path / "narration.wav"
    _write_png(video_path)
    _write_silent_wav(narration_path, 3000)

    project_id = uuid4()
    narration_store = NarrationStore(tmp_path / "narration.sqlite3")
    rough_cut_store = RoughCutStore(tmp_path / "roughcut.sqlite3")
    narration = _track(project_id, 1, narration_path)
    narration_store.save_track(narration)
    plan = _plan(project_id, narration, video_path)
    rough_cut_store.save_plan(plan)

    base_service = TimelineExportService(
        rough_cut_store=rough_cut_store,
        narration_store=narration_store,
        export_root=tmp_path / "exports",
    )
    otio_artifact = base_service.export_otio(plan.id)
    otio_before = otio_artifact.output_path.read_bytes()
    plan_before = rough_cut_store.get_plan(plan.id)
    narration_before = narration_store.get_track(narration.id)

    failing_backend = _FailingBackend()
    failing_service = TimelineExportService(
        rough_cut_store=rough_cut_store,
        narration_store=narration_store,
        export_root=tmp_path / "exports",
        jianying_backend=failing_backend,
    )

    for _ in range(2):
        with pytest.raises(JianyingWriteError, match="forced integration failure"):
            failing_service.export_jianying(
                plan.id,
                draft_name="Will Fail",
                settings=JianyingExportSettings(draft_root=tmp_path / "drafts"),
            )

    assert failing_backend.calls == 2
    assert otio_artifact.output_path.read_bytes() == otio_before
    assert rough_cut_store.get_plan(plan.id) == plan_before
    assert narration_store.get_track(narration.id) == narration_before

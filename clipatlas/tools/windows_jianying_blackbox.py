from __future__ import annotations

import base64
import shutil
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

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

_TOTAL_DURATION_MS = 5000
_FALLBACK_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFElEQVR4nGP8z8DAwMDAxMDAwAIAAwAB/5nQxQAAAABJRU5ErkJggg=="
)


@dataclass(frozen=True)
class BlackboxFixtureResult:
    real_video: bool
    source_path: Path
    narration_path: Path
    plan_id: UUID
    otio_path: Path
    draft_path: Path
    draft_content_path: Path
    total_duration_ms: int


def _write_silent_wav(path: Path, duration_ms: int) -> None:
    sample_rate = 48_000
    frame_count = sample_rate * duration_ms // 1000
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * frame_count)


def _write_fallback_png(path: Path) -> None:
    path.write_bytes(base64.b64decode(_FALLBACK_PNG))


def _try_write_test_video(path: Path) -> bool:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return False
    try:
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=1280x720:rate=30",
                "-t",
                "6",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(path),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        path.unlink(missing_ok=True)
        return False
    return path.is_file() and path.stat().st_size > 0


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


def create_blackbox_fixture(
    *,
    draft_root: Path,
    work_root: Path,
    draft_name: str = "ClipAtlas-Win-Blackbox",
    prefer_ffmpeg: bool = True,
) -> BlackboxFixtureResult:
    """Create an isolated 5-second export fixture without running AI/TTS/retrieval."""

    resolved_draft_root = draft_root.expanduser().resolve()
    if not resolved_draft_root.is_dir():
        raise FileNotFoundError(f"Jianying draft root does not exist: {resolved_draft_root}")

    resolved_work_root = work_root.expanduser().resolve()
    resolved_work_root.mkdir(parents=True, exist_ok=True)

    narration_path = resolved_work_root / "narration.wav"
    _write_silent_wav(narration_path, _TOTAL_DURATION_MS)

    video_path = resolved_work_root / "source.mp4"
    real_video = prefer_ffmpeg and _try_write_test_video(video_path)
    if not real_video:
        video_path = resolved_work_root / "source.png"
        _write_fallback_png(video_path)

    project_id = uuid4()
    narration_store = NarrationStore(resolved_work_root / "narration.sqlite3")
    rough_cut_store = RoughCutStore(resolved_work_root / "roughcut.sqlite3")

    narration = NarrationTrack(
        project_id=project_id,
        source_mode=NarrationSourceMode.TTS,
        script_hash="windows-blackbox",
        provider="blackbox-fixture",
        model="fixture",
        audio_uri=narration_path.as_uri(),
        duration_ms=_TOTAL_DURATION_MS,
        timing_quality=TimingQuality.UNIT_EXACT,
        revision=1,
    )
    narration_store.save_track(narration)

    beat_1 = ScriptBeat(
        project_id=project_id,
        narration_track_id=narration.id,
        sequence=0,
        text="ClipAtlas 黑盒测试第一段。",
        timeline_start_ms=0,
        timeline_end_ms=2000,
        target_duration_ms=2000,
        query_text="blackbox test one",
    )
    beat_2 = ScriptBeat(
        project_id=project_id,
        narration_track_id=narration.id,
        sequence=1,
        text="ClipAtlas 黑盒测试第二段。",
        timeline_start_ms=2000,
        timeline_end_ms=_TOTAL_DURATION_MS,
        target_duration_ms=3000,
        query_text="blackbox test two",
    )

    segment_1 = uuid4()
    segment_2 = uuid4()
    source_uri = video_path.as_uri()
    if real_video:
        source_ranges = ((500, 2500), (3000, 6000))
    else:
        source_ranges = ((0, 2000), (0, 3000))

    clips = [
        RoughCutClip(
            beat_id=beat_1.id,
            segment_id=segment_1,
            video_id=uuid4(),
            source_uri=source_uri,
            source_in_ms=source_ranges[0][0],
            source_out_ms=source_ranges[0][1],
            timeline_in_ms=0,
            timeline_out_ms=2000,
            score=0.90,
            score_breakdown=_score(segment_1, 0.90),
            selection_reason="Windows black-box fixture 1",
        ),
        RoughCutClip(
            beat_id=beat_2.id,
            segment_id=segment_2,
            video_id=uuid4(),
            source_uri=source_uri,
            source_in_ms=source_ranges[1][0],
            source_out_ms=source_ranges[1][1],
            timeline_in_ms=2000,
            timeline_out_ms=_TOTAL_DURATION_MS,
            score=0.88,
            score_breakdown=_score(segment_2, 0.88),
            selection_reason="Windows black-box fixture 2",
        ),
    ]

    plan = RoughCutPlan(
        project_id=project_id,
        narration_track_id=narration.id,
        narration_revision=1,
        revision=1,
        total_duration_ms=_TOTAL_DURATION_MS,
        settings=PlannerSettings(),
        beats=[beat_1, beat_2],
        clips=clips,
    )
    rough_cut_store.save_plan(plan)

    service = TimelineExportService(
        rough_cut_store=rough_cut_store,
        narration_store=narration_store,
        export_root=resolved_work_root / "exports",
        jianying_backend=PyJianYingDraftBackend(),
    )
    otio_artifact = service.export_otio(plan.id)
    jianying_artifact = service.export_jianying(
        plan.id,
        draft_name=draft_name,
        settings=JianyingExportSettings(
            draft_root=resolved_draft_root,
            width=1920,
            height=1080,
        ),
    )
    draft_content_path = jianying_artifact.output_path / "draft_content.json"

    return BlackboxFixtureResult(
        real_video=real_video,
        source_path=video_path,
        narration_path=narration_path,
        plan_id=plan.id,
        otio_path=otio_artifact.output_path,
        draft_path=jianying_artifact.output_path,
        draft_content_path=draft_content_path,
        total_duration_ms=jianying_artifact.total_duration_ms,
    )


__all__ = ["BlackboxFixtureResult", "create_blackbox_fixture"]

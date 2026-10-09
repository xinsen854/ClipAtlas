from itertools import pairwise
from pathlib import Path
from uuid import uuid4

from clipatlas.speech.models import (
    NarrationSourceMode,
    NarrationTrack,
    NarrationUnit,
    TimingQuality,
)
from clipatlas.speech.store import NarrationStore


def test_active_exact_narration_track_is_contiguous_roughcut_clock(tmp_path: Path) -> None:
    store = NarrationStore(tmp_path / "narration.sqlite3")
    project_id = uuid4()
    track = NarrationTrack(
        project_id=project_id,
        source_mode=NarrationSourceMode.TTS,
        script_hash="handoff-script",
        provider="fake",
        model="fake-tts-v0.1",
        audio_uri=(tmp_path / "track.wav").resolve().as_uri(),
        duration_ms=3500,
        timing_quality=TimingQuality.UNIT_EXACT,
        revision=1,
    )
    store.save_track(track)

    windows = [(0, 1200), (1200, 2000), (2000, 3500)]
    for sequence, (start_ms, end_ms) in enumerate(windows):
        store.save_unit(
            NarrationUnit(
                track_id=track.id,
                sequence=sequence,
                text=f"unit-{sequence}",
                text_hash=f"hash-{sequence}",
                start_ms=start_ms,
                end_ms=end_ms,
                audio_uri=(tmp_path / f"unit-{sequence}.wav").resolve().as_uri(),
            )
        )

    assert store.activate_track(project_id, track.id) is True

    active = store.get_active_track(project_id)
    units = store.list_units(track.id)

    assert active == track
    assert units[0].start_ms == 0
    assert units[-1].end_ms == active.duration_ms
    assert all(
        previous.end_ms == current.start_ms
        for previous, current in pairwise(units)
    )

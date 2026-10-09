from pathlib import Path
from uuid import UUID, uuid4

from clipatlas.speech.models import (
    NarrationSourceMode,
    NarrationTrack,
    NarrationUnit,
    NarrationWordTiming,
    RandomMode,
    SpeechProfile,
    TimingQuality,
)
from clipatlas.speech.store import NarrationStore


def _profile(project_id: UUID, *, revision: int, locked: bool = True) -> SpeechProfile:
    return SpeechProfile(
        project_id=project_id,
        provider="fake",
        model="fake-tts",
        voice_id=f"voice-{revision}",
        random_mode=RandomMode.RANDOM_VOICE,
        random_seed=revision,
        locked=locked,
        revision=revision,
    )


def _track(project_id: UUID, *, revision: int, duration_ms: int = 2000) -> NarrationTrack:
    return NarrationTrack(
        project_id=project_id,
        source_mode=NarrationSourceMode.TTS,
        script_hash=f"script-{revision}",
        provider="fake",
        model="fake-tts",
        audio_uri=f"file:///track-{revision}.wav",
        duration_ms=duration_ms,
        timing_quality=TimingQuality.UNIT_EXACT,
        revision=revision,
    )


def test_profile_persists_and_latest_locked_revision_survives_reopen(tmp_path: Path) -> None:
    db_path = tmp_path / "speech.sqlite3"
    project_id = uuid4()
    first = _profile(project_id, revision=1)
    second = _profile(project_id, revision=2)
    store = NarrationStore(db_path)
    store.save_profile(first)
    store.save_profile(second)

    reopened = NarrationStore(db_path)

    assert reopened.get_profile(first.id) == first
    assert reopened.get_profile(second.id) == second
    assert reopened.get_latest_locked_profile(project_id) == second


def test_unlocked_newer_profile_does_not_replace_latest_locked_profile(tmp_path: Path) -> None:
    store = NarrationStore(tmp_path / "speech.sqlite3")
    project_id = uuid4()
    locked = _profile(project_id, revision=1, locked=True)
    unlocked = _profile(project_id, revision=2, locked=False)
    store.save_profile(locked)
    store.save_profile(unlocked)

    assert store.get_latest_locked_profile(project_id) == locked


def test_list_profiles_is_project_scoped_and_newest_revision_first(tmp_path: Path) -> None:
    store = NarrationStore(tmp_path / "speech.sqlite3")
    project_id = uuid4()
    other_project_id = uuid4()
    first = _profile(project_id, revision=1, locked=True)
    second = _profile(project_id, revision=2, locked=False)
    other = _profile(other_project_id, revision=9, locked=True)
    store.save_profile(first)
    store.save_profile(second)
    store.save_profile(other)

    assert store.list_profiles(project_id) == [second, first]
    assert store.list_profiles(uuid4()) == []


def test_track_revisions_and_active_pointer_do_not_delete_history(tmp_path: Path) -> None:
    db_path = tmp_path / "speech.sqlite3"
    project_id = uuid4()
    first = _track(project_id, revision=1)
    second = _track(project_id, revision=2, duration_ms=2500)
    store = NarrationStore(db_path)
    store.save_track(first)
    store.save_track(second)
    store.activate_track(project_id, first.id)
    assert store.get_active_track(project_id) == first

    store.activate_track(project_id, second.id)
    reopened = NarrationStore(db_path)

    assert reopened.get_active_track(project_id) == second
    assert reopened.get_track(first.id) == first
    assert reopened.get_track(second.id) == second
    assert reopened.next_track_revision(project_id) == 3


def test_latest_track_is_used_when_legacy_project_has_no_active_pointer(tmp_path: Path) -> None:
    store = NarrationStore(tmp_path / "speech.sqlite3")
    project_id = uuid4()
    first = _track(project_id, revision=1)
    second = _track(project_id, revision=2, duration_ms=2500)
    store.save_track(first)
    store.save_track(second)

    assert store.get_active_track(project_id) == second


def test_list_tracks_is_project_scoped_and_newest_revision_first(tmp_path: Path) -> None:
    store = NarrationStore(tmp_path / "speech.sqlite3")
    project_id = uuid4()
    other_project_id = uuid4()
    first = _track(project_id, revision=1)
    second = _track(project_id, revision=2, duration_ms=2500)
    other = _track(other_project_id, revision=7)
    store.save_track(first)
    store.save_track(second)
    store.save_track(other)

    assert store.list_tracks(project_id) == [second, first]
    assert store.list_tracks(uuid4()) == []


def test_activate_track_rejects_track_from_other_project(tmp_path: Path) -> None:
    store = NarrationStore(tmp_path / "speech.sqlite3")
    first_project = uuid4()
    second_project = uuid4()
    track = _track(first_project, revision=1)
    store.save_track(track)

    assert store.activate_track(second_project, track.id) is False
    assert store.get_active_track(second_project) is None


def test_unit_checkpoint_and_word_timings_survive_reopen(tmp_path: Path) -> None:
    db_path = tmp_path / "speech.sqlite3"
    project_id = uuid4()
    track = _track(project_id, revision=1)
    first = NarrationUnit(
        track_id=track.id,
        sequence=0,
        text="第一句",
        text_hash="hash-1",
        start_ms=0,
        end_ms=800,
        audio_uri="file:///unit-0.wav",
    )
    second = NarrationUnit(
        track_id=track.id,
        sequence=1,
        text="第二句",
        text_hash="hash-2",
        start_ms=800,
        end_ms=2000,
        audio_uri="file:///unit-1.wav",
    )
    word_b = NarrationWordTiming(
        unit_id=second.id,
        sequence=1,
        word="句",
        start_ms=1100,
        end_ms=1300,
        confidence=0.9,
    )
    word_a = NarrationWordTiming(
        unit_id=second.id,
        sequence=0,
        word="第二",
        start_ms=800,
        end_ms=1100,
        confidence=0.95,
    )
    store = NarrationStore(db_path)
    store.save_track(track)
    store.save_unit(first)
    store.save_unit(second)
    store.save_word_timings([word_b, word_a])

    reopened = NarrationStore(db_path)

    assert reopened.list_units(track.id) == [first, second]
    assert reopened.get_completed_unit(track.id, 0, "hash-1") == first
    assert reopened.get_completed_unit(track.id, 0, "different") is None
    assert reopened.list_word_timings(track.id) == [word_a, word_b]


def test_find_resumable_tts_track_returns_latest_incomplete_matching_checkpoint(
    tmp_path: Path,
) -> None:
    store = NarrationStore(tmp_path / "speech.sqlite3")
    project_id = uuid4()
    profile_id = uuid4()
    other_profile_id = uuid4()
    completed = NarrationTrack(
        project_id=project_id,
        source_mode=NarrationSourceMode.TTS,
        script_hash="same-script",
        speech_profile_id=profile_id,
        provider="fake",
        model="fake-tts",
        audio_uri="file:///completed.wav",
        duration_ms=1200,
        timing_quality=TimingQuality.UNIT_EXACT,
        revision=1,
    )
    wrong_profile = NarrationTrack(
        project_id=project_id,
        source_mode=NarrationSourceMode.TTS,
        script_hash="same-script",
        speech_profile_id=other_profile_id,
        provider="fake",
        model="fake-tts",
        audio_uri=None,
        duration_ms=0,
        timing_quality=TimingQuality.UNIT_EXACT,
        revision=2,
    )
    resumable = NarrationTrack(
        project_id=project_id,
        source_mode=NarrationSourceMode.TTS,
        script_hash="same-script",
        speech_profile_id=profile_id,
        provider="fake",
        model="fake-tts",
        audio_uri=None,
        duration_ms=0,
        timing_quality=TimingQuality.UNIT_EXACT,
        revision=3,
    )
    store.save_track(completed)
    store.save_track(wrong_profile)
    store.save_track(resumable)

    reopened = NarrationStore(tmp_path / "speech.sqlite3")

    assert reopened.find_resumable_tts_track(project_id, "same-script", profile_id) == resumable
    assert reopened.find_resumable_tts_track(project_id, "different-script", profile_id) is None

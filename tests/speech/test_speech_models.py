from uuid import uuid4

import pytest
from pydantic import ValidationError

from clipatlas.speech.models import (
    NarrationSourceMode,
    NarrationTrack,
    NarrationUnit,
    RandomMode,
    SpeechProfile,
    TimingQuality,
    VoiceDescriptor,
    VoiceGender,
)


def test_profile_is_project_scoped_and_can_be_locked() -> None:
    project_id = uuid4()
    profile = SpeechProfile(
        project_id=project_id,
        provider="fake",
        model="fake-tts",
        voice_id="voice-a",
        random_mode=RandomMode.RANDOM_VOICE,
        random_seed=42,
        locked=True,
        speed=1.0,
    )

    assert profile.project_id == project_id
    assert profile.locked is True
    assert profile.random_seed == 42
    assert profile.speed == 1.0


def test_profile_rejects_non_positive_speed() -> None:
    with pytest.raises(ValidationError):
        SpeechProfile(
            project_id=uuid4(),
            provider="fake",
            model="fake-tts",
            voice_id="voice-a",
            speed=0,
        )


def test_track_preserves_real_duration_and_revision() -> None:
    track = NarrationTrack(
        project_id=uuid4(),
        source_mode=NarrationSourceMode.TTS,
        script_hash="abc",
        provider="fake",
        model="fake-tts",
        audio_uri="file:///track.wav",
        duration_ms=1234,
        timing_quality=TimingQuality.UNIT_EXACT,
        revision=2,
    )

    assert track.duration_ms == 1234
    assert track.revision == 2


def test_timed_unit_requires_end_after_start() -> None:
    with pytest.raises(ValidationError, match="end_ms must be greater than start_ms"):
        NarrationUnit(
            track_id=uuid4(),
            sequence=0,
            text="hello",
            text_hash="hash",
            start_ms=100,
            end_ms=100,
            audio_uri="file:///unit.wav",
        )


def test_voice_descriptor_keeps_filter_metadata() -> None:
    voice = VoiceDescriptor(
        provider="fake",
        voice_id="female-warm",
        display_name="Warm Female",
        gender=VoiceGender.FEMALE,
        age_style="young",
        languages=["zh-CN"],
        accents=["mandarin"],
        tags=["warm"],
    )

    assert voice.gender is VoiceGender.FEMALE
    assert voice.languages == ["zh-CN"]
    assert voice.tags == ["warm"]

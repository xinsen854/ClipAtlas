from uuid import uuid4

import pytest

from clipatlas.speech.contracts import SpeechProviderCapabilities
from clipatlas.speech.errors import SpeechConfigurationError
from clipatlas.speech.models import RandomMode, VoiceDescriptor, VoiceGender
from clipatlas.speech.voices import VoiceConstraints, VoiceSelector


def _voices() -> list[VoiceDescriptor]:
    return [
        VoiceDescriptor(
            provider="fake",
            voice_id="m1",
            display_name="Male One",
            gender=VoiceGender.MALE,
            age_style="mature",
            languages=["zh-CN"],
            tags=["serious"],
        ),
        VoiceDescriptor(
            provider="fake",
            voice_id="f1",
            display_name="Female One",
            gender=VoiceGender.FEMALE,
            age_style="young",
            languages=["zh-CN"],
            tags=["warm"],
        ),
        VoiceDescriptor(
            provider="fake",
            voice_id="f2",
            display_name="Female Two",
            gender=VoiceGender.FEMALE,
            age_style="young",
            languages=["en-US"],
            tags=["bright"],
        ),
    ]


def test_random_voice_stays_inside_constraints() -> None:
    selector = VoiceSelector()
    profile = selector.select(
        project_id=uuid4(),
        provider="fake",
        model="fake-tts",
        voices=_voices(),
        constraints=VoiceConstraints(gender=VoiceGender.FEMALE, language="zh-CN"),
        mode=RandomMode.RANDOM_VOICE,
        seed=7,
        capabilities=SpeechProviderCapabilities(speed_control=True),
    )

    assert profile.voice_id == "f1"
    assert profile.gender_constraint is VoiceGender.FEMALE
    assert profile.language == "zh-CN"
    assert profile.locked is True


def test_same_seed_and_pool_are_reproducible() -> None:
    selector = VoiceSelector()
    project_id = uuid4()
    capabilities = SpeechProviderCapabilities(
        speed_control=True,
        pitch_control=True,
        volume_control=True,
    )

    first = selector.select(
        project_id=project_id,
        provider="fake",
        model="fake-tts",
        voices=_voices(),
        constraints=VoiceConstraints(),
        mode=RandomMode.RANDOM_ALL,
        seed=123,
        capabilities=capabilities,
    )
    second = selector.select(
        project_id=project_id,
        provider="fake",
        model="fake-tts",
        voices=list(reversed(_voices())),
        constraints=VoiceConstraints(),
        mode=RandomMode.RANDOM_ALL,
        seed=123,
        capabilities=capabilities,
    )

    assert first.voice_id == second.voice_id
    assert first.speed == second.speed
    assert first.pitch == second.pitch
    assert first.volume == second.volume


def test_random_pitch_uses_positive_ratio_semantics() -> None:
    selector = VoiceSelector()

    profile = selector.select(
        project_id=uuid4(),
        provider="fake",
        model="fake-tts",
        voices=_voices(),
        constraints=VoiceConstraints(),
        mode=RandomMode.RANDOM_PARAMETERS,
        seed=1,
        capabilities=SpeechProviderCapabilities(pitch_control=True),
        voice_id="m1",
    )

    assert profile.pitch is not None
    assert 0.5 <= profile.pitch <= 2.0


def test_random_parameters_preserve_voice_and_only_touch_supported_controls() -> None:
    selector = VoiceSelector()
    profile = selector.select(
        project_id=uuid4(),
        provider="fake",
        model="fake-tts",
        voices=_voices(),
        constraints=VoiceConstraints(),
        mode=RandomMode.RANDOM_PARAMETERS,
        seed=9,
        capabilities=SpeechProviderCapabilities(speed_control=True),
        voice_id="m1",
    )

    assert profile.voice_id == "m1"
    assert profile.speed is not None
    assert profile.pitch is None
    assert profile.volume is None
    assert profile.emotion is None


def test_selector_rejects_empty_eligible_pool() -> None:
    selector = VoiceSelector()

    with pytest.raises(SpeechConfigurationError, match="No eligible voices"):
        selector.select(
            project_id=uuid4(),
            provider="fake",
            model="fake-tts",
            voices=_voices(),
            constraints=VoiceConstraints(gender=VoiceGender.MALE, language="en-US"),
            mode=RandomMode.RANDOM_VOICE,
            seed=1,
            capabilities=SpeechProviderCapabilities(),
        )


def test_locked_profile_is_returned_unchanged_by_reuse_helper() -> None:
    selector = VoiceSelector()
    profile = selector.select(
        project_id=uuid4(),
        provider="fake",
        model="fake-tts",
        voices=_voices(),
        constraints=VoiceConstraints(),
        mode=RandomMode.RANDOM_VOICE,
        seed=55,
        capabilities=SpeechProviderCapabilities(),
    )

    reused = selector.reuse_locked_profile(profile)

    assert reused == profile
    assert reused.id == profile.id


def test_reuse_helper_rejects_unlocked_profile() -> None:
    selector = VoiceSelector()
    profile = selector.select(
        project_id=uuid4(),
        provider="fake",
        model="fake-tts",
        voices=_voices(),
        constraints=VoiceConstraints(),
        mode=RandomMode.RANDOM_VOICE,
        seed=55,
        capabilities=SpeechProviderCapabilities(),
    ).model_copy(update={"locked": False})

    with pytest.raises(SpeechConfigurationError, match="not locked"):
        selector.reuse_locked_profile(profile)

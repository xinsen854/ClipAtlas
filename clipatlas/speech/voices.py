from random import Random
from uuid import UUID

from pydantic import BaseModel, Field

from clipatlas.speech.contracts import SpeechProviderCapabilities
from clipatlas.speech.errors import SpeechConfigurationError
from clipatlas.speech.models import (
    AgeStyle,
    RandomMode,
    SpeechProfile,
    VoiceDescriptor,
    VoiceGender,
)


class VoiceConstraints(BaseModel):
    gender: VoiceGender | None = None
    age_style: AgeStyle | None = None
    language: str | None = None
    accent: str | None = None
    tags: list[str] = Field(default_factory=list)


class VoiceSelector:
    def _eligible(
        self,
        voices: list[VoiceDescriptor],
        *,
        provider: str,
        constraints: VoiceConstraints,
    ) -> list[VoiceDescriptor]:
        eligible: list[VoiceDescriptor] = []
        required_tags = set(constraints.tags)
        for voice in voices:
            if voice.provider != provider:
                continue
            if (
                constraints.gender not in (None, VoiceGender.UNRESTRICTED)
                and voice.gender != constraints.gender
            ):
                continue
            if (
                constraints.age_style not in (None, AgeStyle.UNRESTRICTED)
                and voice.age_style != constraints.age_style
            ):
                continue
            if constraints.language is not None and constraints.language not in voice.languages:
                continue
            if constraints.accent is not None and constraints.accent not in voice.accents:
                continue
            if not required_tags.issubset(voice.tags):
                continue
            eligible.append(voice)
        return sorted(eligible, key=lambda item: (item.provider, item.voice_id))

    def _select_named_voice(
        self,
        eligible: list[VoiceDescriptor],
        voice_id: str,
    ) -> VoiceDescriptor:
        for voice in eligible:
            if voice.voice_id == voice_id:
                return voice
        raise SpeechConfigurationError("Requested voice is not eligible")

    def select(
        self,
        *,
        project_id: UUID,
        provider: str,
        model: str,
        voices: list[VoiceDescriptor],
        constraints: VoiceConstraints,
        mode: RandomMode,
        seed: int,
        capabilities: SpeechProviderCapabilities,
        voice_id: str | None = None,
    ) -> SpeechProfile:
        eligible = self._eligible(voices, provider=provider, constraints=constraints)
        if not eligible:
            raise SpeechConfigurationError("No eligible voices match the requested constraints")

        rng = Random(seed)
        if mode in (RandomMode.RANDOM_VOICE, RandomMode.RANDOM_ALL):
            selected = rng.choice(eligible)
        elif voice_id is not None:
            selected = self._select_named_voice(eligible, voice_id)
        else:
            selected = eligible[0]

        speed: float | None = 1.0
        pitch: float | None = None
        volume: float | None = None
        if mode in (RandomMode.RANDOM_PARAMETERS, RandomMode.RANDOM_ALL):
            if capabilities.speed_control:
                speed = round(rng.uniform(0.9, 1.1), 3)
            if capabilities.pitch_control:
                pitch = round(rng.uniform(0.9, 1.1), 3)
            if capabilities.volume_control:
                volume = round(rng.uniform(0.9, 1.1), 3)

        return SpeechProfile(
            project_id=project_id,
            provider=provider,
            model=model,
            voice_id=selected.voice_id,
            gender_constraint=constraints.gender,
            age_style_constraint=constraints.age_style,
            language=constraints.language,
            accent=constraints.accent,
            speed=speed,
            pitch=pitch,
            volume=volume,
            random_seed=seed,
            random_mode=mode,
            locked=True,
        )

    def reuse_locked_profile(self, profile: SpeechProfile) -> SpeechProfile:
        if not profile.locked:
            raise SpeechConfigurationError("Speech profile is not locked")
        return profile

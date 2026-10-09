import re
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from clipatlas.rules.projector import ProjectTextProjector
from clipatlas.rules.store import ProjectRuleStore
from clipatlas.speech.audio import AudioNormalizer
from clipatlas.speech.contracts import SpeechProvider
from clipatlas.speech.errors import SpeechAudioValidationError, SpeechConfigurationError
from clipatlas.speech.models import (
    NarrationSourceMode,
    NarrationTrack,
    NarrationUnit,
    NarrationWordTiming,
    SpeechProfile,
    SpeechSynthesisRequest,
    TimingQuality,
)
from clipatlas.speech.registry import SpeechProviderRegistry
from clipatlas.speech.request_policy import filter_supported_controls
from clipatlas.speech.store import NarrationStore

_UNIT_SPLIT = re.compile(r"(?<=[。！？!?])|\r?\n+")
_SAFE_FORMAT = re.compile(r"[^a-z0-9]")


def split_narration_units(script: str) -> list[str]:
    return [part.strip() for part in _UNIT_SPLIT.split(script.strip()) if part.strip()]


def _script_hash(script: str) -> str:
    return sha256(script.encode()).hexdigest()


def _text_hash(text: str) -> str:
    return sha256(text.encode()).hexdigest()


def _safe_audio_format(value: str) -> str:
    normalized = _SAFE_FORMAT.sub("", value.lower())
    return normalized or "bin"


class NarrationService:
    def __init__(
        self,
        *,
        store: NarrationStore,
        audio_normalizer: AudioNormalizer,
        narration_root: Path,
        provider: SpeechProvider | None = None,
        registry: SpeechProviderRegistry | None = None,
        rule_store: ProjectRuleStore | None = None,
        sample_rate: int = 48_000,
    ) -> None:
        if sample_rate <= 0:
            raise SpeechConfigurationError("sample_rate must be positive")
        if provider is None and registry is None:
            raise SpeechConfigurationError("speech provider or registry must be configured")
        self._provider = provider
        self._registry = registry
        self._store = store
        self._rule_store = rule_store
        self._rule_projector = ProjectTextProjector()
        self._audio = audio_normalizer
        self._root = narration_root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._sample_rate = sample_rate

    def _resolve_provider(self, project_id: UUID, profile: SpeechProfile) -> SpeechProvider:
        if profile.project_id != project_id:
            raise SpeechConfigurationError("Speech profile belongs to a different project")

        if self._registry is not None:
            try:
                provider = self._registry.get(profile.provider)
            except KeyError as exc:
                raise SpeechConfigurationError(
                    f"Speech profile provider is not registered: {profile.provider}"
                ) from exc
        else:
            runtime_provider = self._provider
            if runtime_provider is None:
                raise SpeechConfigurationError("Speech provider is not configured")
            provider = runtime_provider
            if profile.provider != provider.name:
                raise SpeechConfigurationError(
                    "Speech profile provider does not match runtime provider"
                )

        if profile.model != provider.model:
            raise SpeechConfigurationError("Speech profile model does not match runtime provider")
        return provider

    def _track_root(self, track: NarrationTrack) -> Path:
        return self._root / str(track.project_id) / str(track.id)

    def _unit_path(self, track: NarrationTrack, sequence: int) -> Path:
        return self._track_root(track) / "units" / f"{sequence:04d}.wav"

    def _build_request(
        self,
        text: str,
        profile: SpeechProfile,
        provider: SpeechProvider,
    ) -> SpeechSynthesisRequest:
        request = SpeechSynthesisRequest(
            text=text,
            voice_id=profile.voice_id,
            language=profile.language,
            speed=profile.speed,
            pitch=profile.pitch,
            volume=profile.volume,
            emotion=profile.emotion,
            style=profile.style,
            instruction=profile.instruction,
            output_format="wav",
            sample_rate=self._sample_rate,
        )
        return filter_supported_controls(request, provider.capabilities)

    def _new_track(
        self,
        project_id: UUID,
        script_hash: str,
        profile: SpeechProfile,
        provider: SpeechProvider,
        rule_pack_revision: int | None,
    ) -> NarrationTrack:
        track = NarrationTrack(
            project_id=project_id,
            source_mode=NarrationSourceMode.TTS,
            script_hash=script_hash,
            speech_profile_id=profile.id,
            provider=provider.name,
            model=provider.model,
            rule_pack_revision=rule_pack_revision,
            audio_uri=None,
            duration_ms=0,
            timing_quality=TimingQuality.UNIT_EXACT,
            revision=self._store.next_track_revision(project_id),
        )
        self._store.save_track(track)
        return track

    async def _synthesize_unit(
        self,
        track: NarrationTrack,
        sequence: int,
        canonical_text: str,
        speech_text: str,
        start_ms: int,
        profile: SpeechProfile,
        provider: SpeechProvider,
    ) -> NarrationUnit:
        result = await provider.synthesize(self._build_request(speech_text, profile, provider))
        if not result.audio_bytes:
            raise SpeechAudioValidationError("Speech provider returned empty audio")

        track_root = self._track_root(track)
        raw_root = track_root / ".raw"
        raw_root.mkdir(parents=True, exist_ok=True)
        raw_format = _safe_audio_format(result.output_format)
        raw_path = raw_root / f"{sequence:04d}.{raw_format}"
        raw_path.write_bytes(result.audio_bytes)

        canonical_path = self._unit_path(track, sequence)
        await self._audio.normalize(raw_path, canonical_path, sample_rate=self._sample_rate)
        duration_ms = await self._audio.probe_duration_ms(canonical_path)
        if duration_ms <= 0:
            raise SpeechAudioValidationError("Narration unit duration must be positive")
        raw_path.unlink(missing_ok=True)

        unit = NarrationUnit(
            track_id=track.id,
            sequence=sequence,
            text=canonical_text,
            text_hash=_text_hash(canonical_text),
            start_ms=start_ms,
            end_ms=start_ms + duration_ms,
            source=NarrationSourceMode.TTS,
            audio_uri=canonical_path.resolve().as_uri(),
        )
        self._store.save_unit(unit)

        if result.word_timings:
            self._store.save_word_timings(
                [
                    NarrationWordTiming(
                        unit_id=unit.id,
                        sequence=item.sequence,
                        word=item.word,
                        start_ms=start_ms + item.start_ms,
                        end_ms=start_ms + item.end_ms,
                        confidence=item.confidence,
                    )
                    for item in result.word_timings
                ]
            )
        return unit

    async def create_tts_track(
        self,
        project_id: UUID,
        script: str,
        profile: SpeechProfile,
    ) -> NarrationTrack:
        provider = self._resolve_provider(project_id, profile)
        units_text = split_narration_units(script)
        if not units_text:
            raise SpeechConfigurationError("Narration script must contain text")

        active_pack = self._rule_store.get_active(project_id) if self._rule_store is not None else None
        rule_pack_revision = active_pack.revision if active_pack is not None else None

        script_hash = _script_hash(script)
        self._store.save_profile(profile)
        track = self._store.find_resumable_tts_track(
            project_id,
            script_hash,
            profile.id,
            rule_pack_revision=rule_pack_revision,
        )
        if track is None:
            track = self._new_track(
                project_id,
                script_hash,
                profile,
                provider,
                rule_pack_revision,
            )

        track = track.model_copy(update={"script": script})
        self._store.save_track(track)

        canonical_paths: list[Path] = []
        current_ms = 0
        for sequence, text in enumerate(units_text):
            text_hash = _text_hash(text)
            completed = self._store.get_completed_unit(track.id, sequence, text_hash)
            canonical_path = self._unit_path(track, sequence)
            if completed is not None:
                if not canonical_path.is_file():
                    raise SpeechAudioValidationError(
                        f"Completed narration checkpoint audio is missing: {canonical_path}"
                    )
                current_ms = completed.end_ms or current_ms
                canonical_paths.append(canonical_path)
                continue

            speech_text = (
                self._rule_projector.project(text, active_pack).speech_text
                if active_pack is not None
                else text
            )
            unit = await self._synthesize_unit(
                track,
                sequence,
                text,
                speech_text,
                current_ms,
                profile,
                provider,
            )
            current_ms = unit.end_ms or current_ms
            canonical_paths.append(canonical_path)

        track_path = self._track_root(track) / "track.wav"
        await self._audio.concat(canonical_paths, track_path)
        final_duration_ms = await self._audio.probe_duration_ms(track_path)
        if final_duration_ms <= 0:
            raise SpeechAudioValidationError("Final narration duration must be positive")

        saved_units = self._store.list_units(track.id)
        if saved_units and saved_units[-1].end_ms != final_duration_ms:
            last = saved_units[-1]
            if last.start_ms is None or final_duration_ms <= last.start_ms:
                raise SpeechAudioValidationError("Final narration duration conflicts with unit timeline")
            adjusted = last.model_copy(update={"end_ms": final_duration_ms})
            self._store.save_unit(adjusted)

        completed_track = track.model_copy(
            update={
                "audio_uri": track_path.resolve().as_uri(),
                "duration_ms": final_duration_ms,
                "timing_quality": TimingQuality.UNIT_EXACT,
            }
        )
        self._store.save_track(completed_track)
        if not self._store.activate_track(project_id, completed_track.id):
            raise SpeechAudioValidationError("Failed to activate completed narration track")
        return completed_track

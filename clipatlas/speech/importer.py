from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4, uuid5

from clipatlas.speech.alignment import AlignmentProvider, AlignmentResult, validate_alignment
from clipatlas.speech.audio import AudioNormalizer
from clipatlas.speech.errors import SpeechAudioValidationError, SpeechConfigurationError
from clipatlas.speech.models import (
    NarrationSourceMode,
    NarrationTrack,
    NarrationUnit,
    NarrationWordTiming,
    TimingQuality,
    utc_now,
)
from clipatlas.speech.service import split_narration_units
from clipatlas.speech.store import NarrationStore
from clipatlas.rules.store import ProjectRuleStore


def _hash_text(value: str) -> str:
    return sha256(value.encode()).hexdigest()


class ImportedNarrationService:
    def __init__(
        self,
        *,
        store: NarrationStore,
        audio_normalizer: AudioNormalizer,
        narration_root: Path,
        sample_rate: int = 48_000,
        rule_store: ProjectRuleStore | None = None,
    ) -> None:
        if sample_rate <= 0:
            raise SpeechConfigurationError("sample_rate must be positive")
        self._store = store
        self._audio = audio_normalizer
        self._root = narration_root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._sample_rate = sample_rate
        self._rule_store = rule_store

    def _track_root(self, track: NarrationTrack) -> Path:
        return self._root / str(track.project_id) / str(track.id)

    def _build_units(
        self,
        track: NarrationTrack,
        texts: list[str],
        alignment: AlignmentResult | None,
    ) -> tuple[list[NarrationUnit], list[NarrationWordTiming]]:
        if alignment is None:
            return (
                [
                    NarrationUnit(
                        id=uuid5(track.id, f"unit:{sequence}"),
                        track_id=track.id,
                        sequence=sequence,
                        text=text,
                        text_hash=_hash_text(text),
                        source=NarrationSourceMode.IMPORTED,
                    )
                    for sequence, text in enumerate(texts)
                ],
                [],
            )

        unit_id_by_sequence: dict[int, UUID] = {}
        units: list[NarrationUnit] = []
        for text, timing in zip(texts, alignment.units, strict=True):
            unit = NarrationUnit(
                id=uuid5(track.id, f"unit:{timing.sequence}"),
                track_id=track.id,
                sequence=timing.sequence,
                text=text,
                text_hash=_hash_text(text),
                start_ms=timing.start_ms,
                end_ms=timing.end_ms,
                source=NarrationSourceMode.IMPORTED,
            )
            units.append(unit)
            unit_id_by_sequence[timing.sequence] = unit.id

        words = [
            NarrationWordTiming(
                unit_id=unit_id_by_sequence[item.unit_sequence],
                sequence=item.sequence,
                word=item.word,
                start_ms=item.start_ms,
                end_ms=item.end_ms,
                confidence=item.confidence,
            )
            for item in alignment.words
        ]
        return units, words

    def attach_script(self, track: NarrationTrack, script: str) -> NarrationTrack:
        """New text snapshot over existing imported audio; keep past plans/revisions intact."""
        if track.source_mode != NarrationSourceMode.IMPORTED:
            raise SpeechConfigurationError("Only imported narration can reuse audio with new text")
        if track.script_hash == _hash_text(script):
            return track
        texts = split_narration_units(script)
        if not texts:
            raise SpeechConfigurationError("Narration script must contain text")
        updated = track.model_copy(update={
            "id": uuid4(), "script": script, "script_hash": _hash_text(script),
            "revision": self._store.next_track_revision(track.project_id),
            "created_at": utc_now(), "timing_quality": TimingQuality.TRACK_ONLY,
            "alignment_source_id": None, "alignment_notes": [],
        })
        units, _ = self._build_units(updated, texts, None)
        self._store.save_track(updated)
        for unit in units:
            self._store.save_unit(unit)
        if not self._store.activate_track(track.project_id, updated.id):
            raise SpeechAudioValidationError("Failed to activate narration text revision")
        return updated

    async def import_track(
        self,
        project_id: UUID,
        source_path: Path,
        script: str,
        aligner: AlignmentProvider | None = None,
        *,
        activate: bool = True,
        track_id: UUID | None = None,
    ) -> NarrationTrack:
        source = source_path.resolve()
        if not source.is_file():
            raise SpeechAudioValidationError(f"Imported narration source does not exist: {source}")

        texts = split_narration_units(script)
        if not texts:
            raise SpeechConfigurationError("Imported narration script must contain text")

        locked_rule_revision: int | None = None
        if self._rule_store is not None:
            pack = self._rule_store.get_active(project_id)
            locked_rule_revision = pack.revision if pack is not None else None

        track = NarrationTrack(
            id=track_id or uuid4(),
            project_id=project_id,
            source_mode=NarrationSourceMode.IMPORTED,
            script_hash=_hash_text(script),
            script=script,
            audio_uri=None,
            duration_ms=0,
            timing_quality=TimingQuality.TRACK_ONLY,
            rule_pack_revision=locked_rule_revision,
            revision=self._store.next_track_revision(project_id),
        )
        track_root = self._track_root(track)
        canonical_path = track_root / "track.wav"
        await self._audio.normalize(source, canonical_path, sample_rate=self._sample_rate)
        duration_ms = await self._audio.probe_duration_ms(canonical_path)
        if duration_ms <= 0:
            raise SpeechAudioValidationError("Imported narration duration must be positive")

        alignment: AlignmentResult | None = None
        quality = TimingQuality.TRACK_ONLY
        if aligner is not None:
            candidate = await aligner.align(canonical_path, texts)
            if candidate is not None:
                alignment = validate_alignment(
                    candidate,
                    unit_count=len(texts),
                    duration_ms=duration_ms,
                )
                quality = TimingQuality.ALIGNED

        completed_track = track.model_copy(
            update={
                "audio_uri": canonical_path.resolve().as_uri(),
                "duration_ms": duration_ms,
                "timing_quality": quality,
            }
        )
        units, words = self._build_units(completed_track, texts, alignment)

        self._store.save_track(completed_track)
        for unit in units:
            self._store.save_unit(unit)
        if words:
            self._store.save_word_timings(words)
        if activate and not self._store.activate_track(project_id, completed_track.id):
            raise SpeechAudioValidationError("Failed to activate imported narration track")
        return completed_track

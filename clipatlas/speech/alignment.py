from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field, model_validator

from clipatlas.speech.errors import SpeechAudioValidationError


class AlignmentUnitTiming(BaseModel):
    sequence: int = Field(ge=0)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_range(self) -> "AlignmentUnitTiming":
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        return self


class AlignmentWordTiming(BaseModel):
    unit_sequence: int = Field(ge=0)
    sequence: int = Field(ge=0)
    word: str = Field(min_length=1)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_range(self) -> "AlignmentWordTiming":
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        return self


class AlignmentResult(BaseModel):
    units: list[AlignmentUnitTiming] = Field(default_factory=list)
    words: list[AlignmentWordTiming] = Field(default_factory=list)


class NarrationAlignmentMap(BaseModel):
    """Observed audio timing for an immutable source-text unit."""

    source_unit_id: str
    source_quote: str = Field(min_length=1)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    asr_sentence_ids: list[str] = Field(default_factory=list)
    alignment_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    alignment_basis: str = "observed_word_times"

    @model_validator(mode="after")
    def validate_range(self) -> "NarrationAlignmentMap":
        if self.end_ms <= self.start_ms:
            raise ValueError("alignment map end_ms must be greater than start_ms")
        return self


@runtime_checkable
class AlignmentProvider(Protocol):
    async def align(
        self,
        audio_path: Path,
        script_units: list[str],
    ) -> AlignmentResult | None: ...


def validate_alignment(
    result: AlignmentResult,
    *,
    unit_count: int,
    duration_ms: int,
) -> AlignmentResult:
    if duration_ms <= 0:
        raise SpeechAudioValidationError("Narration duration must be positive")
    if len(result.units) != unit_count:
        raise SpeechAudioValidationError("Alignment must cover every narration unit")

    units = sorted(result.units, key=lambda item: item.sequence)
    if [unit_timing.sequence for unit_timing in units] != list(range(unit_count)):
        raise SpeechAudioValidationError("Alignment unit sequences must be contiguous")

    previous_end = 0
    unit_by_sequence: dict[int, AlignmentUnitTiming] = {}
    for unit_timing in units:
        if unit_timing.start_ms < previous_end:
            raise SpeechAudioValidationError("Alignment unit ranges must not overlap")
        if unit_timing.end_ms > duration_ms:
            raise SpeechAudioValidationError("Alignment unit range exceeds narration duration")
        previous_end = unit_timing.end_ms
        unit_by_sequence[unit_timing.sequence] = unit_timing

    words = sorted(result.words, key=lambda item: (item.unit_sequence, item.sequence))
    previous_word_end_by_unit: dict[int, int] = {}
    previous_word_sequence_by_unit: dict[int, int] = {}
    for word_timing in words:
        unit = unit_by_sequence.get(word_timing.unit_sequence)
        if unit is None:
            raise SpeechAudioValidationError("Alignment word references an unknown unit")
        previous_sequence = previous_word_sequence_by_unit.get(word_timing.unit_sequence, -1)
        if word_timing.sequence != previous_sequence + 1:
            raise SpeechAudioValidationError("Alignment word sequences must be contiguous")
        previous_end = previous_word_end_by_unit.get(word_timing.unit_sequence, unit.start_ms)
        if word_timing.start_ms < previous_end:
            raise SpeechAudioValidationError("Alignment word ranges must not overlap")
        if word_timing.start_ms < unit.start_ms or word_timing.end_ms > unit.end_ms:
            raise SpeechAudioValidationError("Alignment word range must stay inside its unit")
        previous_word_sequence_by_unit[word_timing.unit_sequence] = word_timing.sequence
        previous_word_end_by_unit[word_timing.unit_sequence] = word_timing.end_ms

    return AlignmentResult(units=units, words=words)

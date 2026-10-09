"""Map director units onto timed beats by spoken-text overlap.

Pure local logic: the unit's ``text_range`` (quoted by the API from the
finalised script) is located inside the concatenated beat text, either as a
whole span or by its individual sentences, and translated into an inclusive
beat-index range.
"""

import re
from collections.abc import Sequence

from clipatlas.director.models import DirectorUnit
from clipatlas.roughcut.models import ScriptBeat

_SENTENCE_SPLIT = re.compile(r"[。！？!?\n]+")
_PUNCTUATION = re.compile(r"[，。！？；、,.;!?:\s]+")


def _normalized(text: str) -> str:
    return _PUNCTUATION.sub("", text)


def _split_sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_SPLIT.split(text) if part.strip()]


def map_units_to_beats(
    beats: Sequence[ScriptBeat],
    units: Sequence[DirectorUnit],
) -> list[DirectorUnit]:
    """Return units with ``beat_range`` filled (inclusive beat indexes).

    Units whose text_range cannot be located are returned unchanged (beat_range
    stays None) so callers can decide whether to keep or drop them.
    """
    if not beats:
        return list(units)

    normalized_beats = [_normalized(beat.text) for beat in beats]
    offsets: list[int] = []
    cursor = 0
    for text in normalized_beats:
        offsets.append(cursor)
        cursor += len(text) + 1  # +1 for the separator
    joined = "\n".join(normalized_beats)

    mapped: list[DirectorUnit] = []
    for unit in units:
        span = _locate(_normalized(unit.text_range), joined)
        if span is not None:
            start_pos, end_pos = span
            beat_range = _position_to_beat_range(start_pos, end_pos, offsets)
        else:
            beat_range = _fallback_beat_range(unit, joined, offsets, normalized_beats)
        if beat_range is None:
            mapped.append(unit)
            continue
        mapped.append(unit.model_copy(update={"beat_range": beat_range}))
    return mapped


def _fallback_beat_range(
    unit: DirectorUnit,
    joined: str,
    offsets: list[int],
    normalized_beats: list[str],
) -> tuple[int, int] | None:
    """Sentence-level fallback: exact sentence positions, or a beat whose text
    is contained in a sentence (handles conjunction prefixes like "然后…")."""
    matched_beats: set[int] = set()
    for sentence in _split_sentences(unit.text_range):
        normalized = _normalized(sentence)
        if not normalized:
            continue
        position = joined.find(normalized)
        if position >= 0:
            matched_beats.add(_position_to_beat_index(position, offsets))
            continue
        for index, beat_text in enumerate(normalized_beats):
            if beat_text and beat_text in normalized:
                matched_beats.add(index)
    if not matched_beats:
        return None
    return min(matched_beats), max(matched_beats)


def _position_to_beat_index(position: int, offsets: list[int]) -> int:
    for index in range(len(offsets) - 1, -1, -1):
        if position >= offsets[index]:
            return index
    return 0


def _locate(needle: str, joined: str) -> tuple[int, int] | None:
    if not needle:
        return None
    start = joined.find(needle)
    if start < 0:
        return None
    return start, start + len(needle)


def _position_to_beat_range(start_pos: int, end_pos: int, offsets: list[int]) -> tuple[int, int]:
    start_beat = 0
    for index in range(len(offsets) - 1, -1, -1):
        if start_pos >= offsets[index]:
            start_beat = index
            break
    end_beat = start_beat
    for index in range(len(offsets) - 1, -1, -1):
        if end_pos - 1 >= offsets[index]:
            end_beat = index
            break
    return start_beat, end_beat

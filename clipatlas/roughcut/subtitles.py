"""Rule-aware subtitle generation for a rough cut.

Subtitles follow the narration beats. Each beat's text is projected through
the project's active rule pack (``subtitle_replace`` rules only: terms that
must not appear on screen, e.g. broadcast-norm restricted wording, are removed
or replaced while the narration audio is unaffected) and then split into
segments at punctuation, with the punctuation removed. Each segment becomes
its own subtitle; the beat's timeline window is distributed across segments in
proportion to their character counts, so the subtitles stay aligned to the
narration that reads them.

No API is called here; the projection is pure local text replacement.
"""

import re
from collections.abc import Iterable, Sequence

from clipatlas.roughcut.models import RoughCutSubtitle, ScriptBeat
from clipatlas.rules.models import ProjectRulePack
from clipatlas.rules.projector import ProjectTextProjector

# Punctuation that ends a subtitle segment. Punctuation marks are dropped from
# the visible text; the split points only decide where one segment ends and
# the next begins (and how the beat's time window is divided).
# - 、(enumeration comma) does NOT split: "商务、家用、旷野" reads better as
#   one subtitle than three flashing fragments.
# - quote marks are removed but never split: "座舱采用"一舱三境"设计" should
#   stay one subtitle.
_SPLIT_RE = re.compile(r"[。！？；，：…—～·]+")
_QUOTES = str.maketrans("", "", "“”‘’\"'")
# A segment shorter than this is glued onto its neighbour so a subtitle never
# flashes a single dangling character.
_MIN_SEGMENT_CHARS = 2
# Segments longer than this (unlikely once punctuation splits the beat) are
# hard-split so no single subtitle overflows the screen.
_MAX_SUBTITLE_CHARS = 26


def _clean_line(text: str) -> str:
    return " ".join(text.split())


def _hard_split_long(text: str, max_chars: int = _MAX_SUBTITLE_CHARS) -> list[str]:
    out: list[str] = []
    while len(text) > max_chars:
        cut = text.rfind(" ", 0, max_chars)
        if cut <= 0:
            cut = max_chars
        out.append(text[:cut])
        text = text[cut:].lstrip()
    if text:
        out.append(text)
    return out


def split_by_punctuation(text: str) -> list[str]:
    """Split text at punctuation, dropping the punctuation marks.

    Spaces are normalised but never split (model names like "ADS 5.0 MAX"
    must stay together); over-long segments fall back to a space-aware
    hard split.
    """
    text = _clean_line(text)
    if not text:
        return []
    text = text.translate(_QUOTES)
    parts = [part.strip() for part in _SPLIT_RE.split(text)]
    parts = [part for part in parts if part]
    merged: list[str] = []
    for part in parts:
        if merged and len(part) < _MIN_SEGMENT_CHARS:
            merged[-1] = merged[-1] + part
        else:
            merged.append(part)
    # Punctuation that was not a split point (、) is still dropped from the
    # visible text per the "no punctuation on screen" rule.
    final: list[str] = []
    for part in merged:
        part = part.replace("、", "")
        final.extend(_hard_split_long(part))
    return final


def _assign_windows(
    parts: Sequence[str], start_ms: int, end_ms: int
) -> list[tuple[str, int, int]]:
    """Distribute [start_ms, end_ms) across parts proportional to length."""
    total = sum(len(part) for part in parts) or 1
    duration = end_ms - start_ms
    windows: list[tuple[str, int, int]] = []
    cursor = start_ms
    for part in parts:
        span = round(duration * len(part) / total)
        stop = min(end_ms, cursor + span)
        windows.append((part, cursor, stop))
        cursor = stop
    if windows and windows[-1][2] < end_ms:
        last = windows[-1]
        windows[-1] = (last[0], last[1], end_ms)
    return windows


def build_subtitles(
    beats: Sequence[ScriptBeat],
    pack: ProjectRulePack | None,
    projector: ProjectTextProjector | None = None,
) -> list[RoughCutSubtitle]:
    """Build rule-projected, punctuation-split subtitles for the beats.

    Beats are sorted by timeline start; empty projected text (fully replaced)
    is skipped; consecutive subtitles with identical text are merged so the
    same line does not blink off between them.
    """
    active_projector = projector or ProjectTextProjector()
    ordered = sorted(beats, key=lambda beat: (beat.timeline_start_ms, beat.timeline_end_ms))

    subtitles: list[RoughCutSubtitle] = []
    for beat in ordered:
        if beat.kind == "visual_only":
            continue
        if pack is not None:
            projected = active_projector.project(beat.text, pack)
            parts = split_by_punctuation(projected.subtitle_text)
        else:
            parts = split_by_punctuation(beat.text)
        if not parts:
            continue
        for text, start_ms, end_ms in _assign_windows(
            parts, beat.timeline_start_ms, beat.timeline_end_ms
        ):
            if (
                subtitles
                and subtitles[-1].text == text
                and subtitles[-1].end_ms == start_ms
            ):
                subtitles[-1] = subtitles[-1].model_copy(update={"end_ms": end_ms})
                continue
            subtitles.append(RoughCutSubtitle(text=text, start_ms=start_ms, end_ms=end_ms))

    return subtitles


def merge_adjacent_identical(
    subtitles: Iterable[RoughCutSubtitle],
) -> list[RoughCutSubtitle]:
    """Merge touching subtitles with identical text (safety helper)."""
    merged: list[RoughCutSubtitle] = []
    for subtitle in subtitles:
        if (
            merged
            and merged[-1].text == subtitle.text
            and merged[-1].end_ms == subtitle.start_ms
        ):
            merged[-1] = merged[-1].model_copy(update={"end_ms": subtitle.end_ms})
        else:
            merged.append(subtitle)
    return merged

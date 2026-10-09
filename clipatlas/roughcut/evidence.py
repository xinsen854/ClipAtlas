"""Local checks against the actual source window used on the timeline."""

from clipatlas.director.local_fit import fit
from clipatlas.director.models import DirectorUnit
from clipatlas.domain.models import SemanticAnnotation
from clipatlas.domain.visual_protocol import normalize_match_level
from clipatlas.roughcut.contracts import RoughCutSearchHit
from clipatlas.roughcut.models import RoughCutClip
from clipatlas.speech.models import NarrationWordTiming


def spoken_anchor_offset_ms(
    text: str,
    anchor_phrase: str | None,
    duration_ms: int,
) -> int | None:
    """Estimate when an exact spoken phrase occurs inside one narration beat.

    The narration store does not always contain word-level timing. When it
    does not, use the phrase's position among spoken alpha-numeric/CJK
    characters as a deterministic local estimate. This never changes source
    evidence truth; it only decides where a retained evidence anchor should sit
    inside the selected shot.
    """
    if duration_ms <= 0 or not anchor_phrase:
        return None
    index = text.find(anchor_phrase)
    if index < 0:
        return None

    def spoken_weight(value: str) -> int:
        return sum(1 for character in value if character.isalnum())

    total = spoken_weight(text)
    anchor_weight = spoken_weight(anchor_phrase)
    if total <= 0 or anchor_weight <= 0:
        return None
    before = spoken_weight(text[:index])
    ratio = (before + anchor_weight / 2) / total
    return min(duration_ms, max(0, round(duration_ms * ratio)))


def _spoken_token(value: str) -> str:
    return "".join(character.casefold() for character in value if character.isalnum())


def exact_spoken_anchor_offset_ms(
    anchor_phrase: str | None,
    *,
    beat_start_ms: int,
    beat_end_ms: int,
    word_timings: list[NarrationWordTiming],
) -> int | None:
    """Locate an anchor phrase against real provider word/phrase timings.

    Provider timing tokens are absolute on the narration track. The returned
    offset is relative to the current visual beat and therefore can be passed
    directly to ``source_window``. Punctuation/spacing/case differences are
    ignored, but no fuzzy semantic match is attempted: if the exact spoken
    phrase cannot be reconstructed from stored timing tokens, return ``None``
    so the deterministic text-position estimate remains the fallback.
    """
    if not anchor_phrase or beat_end_ms <= beat_start_ms or not word_timings:
        return None
    normalized_anchor = _spoken_token(anchor_phrase)
    if not normalized_anchor:
        return None

    eligible = sorted(
        (
            item for item in word_timings
            if item.end_ms > beat_start_ms and item.start_ms < beat_end_ms
        ),
        key=lambda item: (item.start_ms, item.end_ms, item.sequence),
    )
    stream: list[str] = []
    owners: list[NarrationWordTiming] = []
    for item in eligible:
        token = _spoken_token(item.word)
        if not token:
            continue
        stream.extend(token)
        owners.extend([item] * len(token))
    if not stream:
        return None

    normalized_stream = "".join(stream)
    index = normalized_stream.find(normalized_anchor)
    if index < 0:
        return None
    end_index = index + len(normalized_anchor) - 1
    if end_index >= len(owners):
        return None
    first = owners[index]
    last = owners[end_index]
    centre_ms = round((first.start_ms + last.end_ms) / 2)
    duration_ms = beat_end_ms - beat_start_ms
    return min(duration_ms, max(0, centre_ms - beat_start_ms))


def _director_anchor_target_ms(
    units: list[DirectorUnit] | None,
    duration: int,
) -> int | None:
    """Use the strongest S/A Director anchor when word timing is unavailable."""
    if not units:
        return None
    ordered = sorted(
        units,
        key=lambda unit: ({"S": 0, "A": 1, "B": 2}.get(unit.importance, 3), unit.text_range),
    )
    for unit in ordered:
        if unit.importance not in {"S", "A"}:
            continue
        offset = spoken_anchor_offset_ms(unit.text_range, unit.anchor_phrase, duration)
        if offset is not None:
            return offset
    return None


def source_window(
    hit: RoughCutSearchHit,
    duration: int,
    units: list[DirectorUnit] | None = None,
    *,
    anchor_target_offset_ms: int | None = None,
) -> tuple[int, int]:
    start = hit.source_start_ms
    anchor_start = getattr(hit, "anchor_start_ms", None)
    anchor_end = getattr(hit, "anchor_end_ms", None)
    target_offset = anchor_target_offset_ms
    if target_offset is None:
        target_offset = getattr(hit, "spoken_anchor_target_ms", None)
    if target_offset is None:
        target_offset = _director_anchor_target_ms(units, duration)
    if anchor_start is not None and anchor_end is not None:
        # Legal starts that retain the complete source evidence anchor.
        lower = max(start, anchor_end - duration)
        upper = min(anchor_start, hit.source_end_ms - duration)
        if lower <= upper:
            if target_offset is not None:
                target = min(duration, max(0, target_offset))
                anchor_center = (anchor_start + anchor_end) / 2
                desired = round(anchor_center - target)
                start = min(max(desired, lower), upper)
            else:
                # Preserve the previous deterministic behaviour when no spoken
                # phrase timing is available.
                start = lower
    typed_units = [unit for unit in units or [] if unit.claims]
    if typed_units:
        lower = max(hit.source_start_ms, getattr(hit, "safe_start_ms", None) or hit.source_start_ms)
        upper = min(hit.source_end_ms, getattr(hit, "safe_end_ms", None) or hit.source_end_ms) - duration
        if lower <= upper:
            candidates = {min(max(start, lower), upper)}
            for fact in hit.annotation.facts:
                if fact.start_ms is not None and fact.end_ms is not None:
                    candidates.update((min(max(fact.start_ms, lower), upper),
                                       min(max(fact.end_ms - duration, lower), upper)))
            def rank(position):
                matches = [m for unit in typed_units for m in fit(
                    unit, hit.annotation, source_window=(position, position + duration),
                    allow_untimed=False,
                ).claim_matches]
                return (sum(m.importance == "S" and m.level == "DIRECT" for m in matches),
                        sum(m.level == "DIRECT" for m in matches),
                        sum(m.level == "SUPPORT" for m in matches), -abs(position-start))
            start = max(sorted(candidates), key=rank)
    return start, start + duration


def anchor_retained(clip: RoughCutClip) -> bool | None:
    if clip.anchor_in_ms is None and clip.anchor_out_ms is None:
        return None
    return (
        clip.anchor_in_ms is not None and clip.anchor_out_ms is not None
        and clip.source_in_ms <= clip.anchor_in_ms < clip.anchor_out_ms <= clip.source_out_ms
    )


def finalize_evidence(
    clip: RoughCutClip, hit: RoughCutSearchHit, units: list[DirectorUnit],
) -> RoughCutClip:
    retained = anchor_retained(clip)
    complete_segment = (
        clip.source_in_ms == hit.source_start_ms and clip.source_out_ms == hit.source_end_ms
    )
    annotation = hit.annotation
    # Untimed labels describe their original segment, never every point of an
    # expanded span. Only an intact anchor (or intact unexpanded segment) can
    # carry those labels into the final fit check.
    allow_untimed = retained is True or (retained is None and complete_segment)
    if not allow_untimed:
        annotation = SemanticAnnotation(
            segment_id=annotation.segment_id, origin=annotation.origin,
            description=annotation.description,
            facts=[f for f in annotation.facts if f.start_ms is not None and f.end_ms is not None],
        )
    verdicts = [fit(unit, annotation, source_window=(clip.source_in_ms, clip.source_out_ms),
                    allow_untimed=allow_untimed)
                for unit in units]
    claim_matches = [match for verdict in verdicts for match in verdict.claim_matches]
    matched = list(dict.fromkeys(requirement for verdict in verdicts for requirement in (
        *verdict.matched_must_have, *verdict.matched_subjects,
        *verdict.matched_objects, *verdict.matched_actions,
    )))
    missing = list(dict.fromkeys(
        requirement for unit, verdict in zip(units, verdicts) for requirement in (
            *verdict.missing_must_have,
            *(r for r in unit.required_subjects if r not in verdict.matched_subjects),
            *(r for r in unit.required_objects if r not in verdict.matched_objects),
            *(r for r in unit.required_actions if r not in verdict.matched_actions),
        )
    ))
    priority = {"REJECT": 0, "UNKNOWN": 1, "SUPPORT": 2, "DIRECT": 3}
    level = min((v.level for v in verdicts), key=priority.__getitem__) if verdicts else None
    if claim_matches and all(unit.claims for unit in units):
        from clipatlas.director.claim_matching import summarize_matches
        level = summarize_matches(claim_matches)
    reasons = []
    if ((clip.safe_in_ms is not None and clip.source_in_ms < clip.safe_in_ms)
            or (clip.safe_out_ms is not None and clip.source_out_ms > clip.safe_out_ms)):
        reasons.append("final window exceeds the annotated safe range")
        if level == "DIRECT":
            level = "UNKNOWN"
            matched = []
    if retained is False:
        reasons.append("final window does not retain the complete evidence anchor")
        if level == "DIRECT" and not claim_matches:
            level = "UNKNOWN"
            matched = []
    if units and level != "DIRECT":
        reasons.append("final window does not prove all Director requirements")
    schedule = clip.schedule_level
    if claim_matches and all(unit.claims for unit in units) and schedule in {"exact", "related", "source"}:
        schedule = (
            "exact" if all(match.level == "DIRECT" for match in claim_matches)
            else "related" if any(match.level in {"DIRECT", "SUPPORT"} for match in claim_matches)
            else "source"
        )
    if ((level not in {None, "DIRECT"}) or (reasons and not claim_matches)) and schedule == "exact":
        schedule = "related" if level == "SUPPORT" else "source"
    return clip.model_copy(update={
        "director_fit": level,
        "director_matched_requirements": matched,
        "director_missing_requirements": missing,
        "evidence_retained": retained,
        "evidence_check_reasons": reasons,
        "schedule_level": schedule,
        "match_level": normalize_match_level(schedule, level),
        "claim_matches": claim_matches,
    })
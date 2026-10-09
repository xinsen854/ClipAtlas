"""Deterministic global candidate assignment for rough-cut planning.

The allocator is deliberately conservative.  It does not create semantic
truth: DIRECT/SUPPORT/etc. must already have been decided by local evidence
rules.  Its job is to protect scarce S evidence, keep complete sentences on
long continuous shots when possible, avoid source-range repetition, and apply
batch cooldown without turning cooldown into a hard failure.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal
from uuid import UUID

Importance = Literal["S", "A", "B"]


@dataclass(frozen=True, slots=True)
class AssignmentCandidate:
    requirement_id: str
    sentence_id: str
    importance: Importance
    video_id: UUID
    start_ms: int
    end_ms: int
    score: float
    match_level: str
    anchor_start_ms: int | None = None
    anchor_end_ms: int | None = None
    pollution_level: str | None = None
    schedule_level: str | None = None
    controlled_reuse: bool = False

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)

    @property
    def has_anchor(self) -> bool:
        return (
            self.anchor_start_ms is not None
            and self.anchor_end_ms is not None
            and self.start_ms <= self.anchor_start_ms < self.anchor_end_ms <= self.end_ms
        )


_LEVEL_RANK = {
    "DIRECT": 0,
    "SUPPORT": 1,
    "RELATED": 2,
    "GENERIC": 3,
    "SOURCE": 4,
    "REUSE": 5,
    "UNKNOWN": 6,
}
_IMPORTANCE_RANK = {"S": 0, "A": 1, "B": 2}


def _overlap_ms(left_start: int, left_end: int, right_start: int, right_end: int) -> int:
    return max(0, min(left_end, right_end) - max(left_start, right_start))


def _is_legal(candidate: AssignmentCandidate) -> bool:
    if candidate.end_ms <= candidate.start_ms:
        return False
    if candidate.pollution_level == "blocked":
        return False
    if candidate.match_level == "REJECT":
        return False
    return True


def _same_output_conflict(
    candidate: AssignmentCandidate,
    selected: list[AssignmentCandidate],
) -> bool:
    return any(
        prior.video_id == candidate.video_id
        and _overlap_ms(prior.start_ms, prior.end_ms, candidate.start_ms, candidate.end_ms) > 0
        for prior in selected
    )


def _batch_occupancy(
    candidate: AssignmentCandidate,
    batch_usage: dict[str, list[tuple[int, int, int]]] | None,
    *,
    current_batch_index: int,
    reuse_gap: int,
) -> int:
    if not batch_usage:
        return 0
    overlaps = 0
    for start_ms, end_ms, used_index in batch_usage.get(str(candidate.video_id), []):
        if current_batch_index - used_index >= reuse_gap:
            continue
        if _overlap_ms(start_ms, end_ms, candidate.start_ms, candidate.end_ms) >= 1000:
            overlaps += 1
    return overlaps


def _requirement_order(
    candidate_groups: dict[str, list[AssignmentCandidate]],
) -> list[str]:
    """Reserve the requirements with the fewest S/DIRECT alternatives first."""

    rows: list[tuple[int, int, int, str]] = []
    for requirement_id, raw in candidate_groups.items():
        legal = [candidate for candidate in raw if _is_legal(candidate)]
        direct = [candidate for candidate in legal if candidate.match_level == "DIRECT"]
        importance = min(
            (_IMPORTANCE_RANK.get(candidate.importance, 2) for candidate in legal),
            default=2,
        )
        # S requirements with one DIRECT candidate should be allocated before a
        # broad sentence with ten interchangeable DIRECT candidates.
        scarcity = len(direct) if direct else 10_000 + len(legal)
        rows.append((importance, scarcity, len(legal), requirement_id))
    return [requirement_id for *_, requirement_id in sorted(rows)]


def _candidate_key(
    candidate: AssignmentCandidate,
    *,
    occupied: int,
    required_duration_ms: int | None,
) -> tuple[int, int, int, int, float, int, str, int]:
    level = _LEVEL_RANK.get(candidate.match_level, 6)
    full_sentence = (
        0
        if required_duration_ms is None or candidate.duration_ms >= required_duration_ms
        else 1
    )
    # An S/A evidence anchor is valuable because the final trim can align the
    # spoken selling point with the exact local evidence interval.
    anchor_rank = 0 if candidate.has_anchor and candidate.importance in {"S", "A"} else 1
    return (
        level,
        full_sentence,
        anchor_rank,
        occupied,
        -candidate.score,
        -candidate.duration_ms,
        str(candidate.video_id),
        candidate.start_ms,
    )


def assign_requirements(
    candidate_groups: dict[str, list[AssignmentCandidate]],
    *,
    required_duration_ms: dict[str, int] | None = None,
    batch_usage: dict[str, list[tuple[int, int, int]]] | None = None,
    current_batch_index: int = 0,
    reuse_gap: int = 5,
) -> dict[str, AssignmentCandidate]:
    """Assign one primary continuous candidate per requirement.

    Rules, in order:
    1. blocked/REJECT/illegal ranges never participate;
    2. scarce S/DIRECT requirements reserve their evidence first;
    3. source ranges cannot overlap inside one output;
    4. DIRECT > SUPPORT > RELATED > GENERIC > SOURCE > REUSE;
    5. a candidate long enough for the complete sentence beats a short fragment;
    6. an S/A candidate carrying an explicit evidence anchor is preferred;
    7. within the batch cooldown, an unused 0.75 candidate beats an otherwise
       equivalent recently-used 0.80 candidate;
    8. cooldown is relaxed only when no legal unoccupied alternative exists.

    The function intentionally returns no entry for a requirement that has no
    non-overlapping legal candidate.  The planner then continues the explicit
    generic → source → reuse fallback ladder instead of silently duplicating an
    already-used source range in the same output.
    """

    if reuse_gap < 1:
        raise ValueError("reuse_gap must be at least 1")

    selected: dict[str, AssignmentCandidate] = {}
    selected_ranges: list[AssignmentCandidate] = []
    durations = required_duration_ms or {}

    for requirement_id in _requirement_order(candidate_groups):
        legal = [
            candidate
            for candidate in candidate_groups.get(requirement_id, [])
            if _is_legal(candidate)
            and not _same_output_conflict(candidate, selected_ranges)
        ]
        if not legal:
            continue

        occupancy = {
            id(candidate): _batch_occupancy(
                candidate,
                batch_usage,
                current_batch_index=current_batch_index,
                reuse_gap=reuse_gap,
            )
            for candidate in legal
        }
        fresh = [candidate for candidate in legal if occupancy[id(candidate)] == 0]
        pool = fresh or legal
        best = min(
            pool,
            key=lambda candidate: _candidate_key(
                candidate,
                occupied=occupancy[id(candidate)],
                required_duration_ms=durations.get(requirement_id),
            ),
        )
        if not fresh and occupancy[id(best)] > 0:
            best = replace(best, controlled_reuse=True)
        selected[requirement_id] = best
        selected_ranges.append(best)

    return selected

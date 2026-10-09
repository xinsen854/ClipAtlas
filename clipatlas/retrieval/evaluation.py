"""Offline recall metrics for the candidate-first development phase."""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RecallWindow:
    video_id: UUID
    start_ms: int
    end_ms: int


def recall_at_k(
    expected: Sequence[RecallWindow],
    candidates: Sequence[RecallWindow],
    *,
    k: int = 20,
    overlap_ratio: float = 0.5,
) -> float:
    """Return whether each expected window is represented in the first k hits.

    This is deliberately a candidate-coverage metric, not an exact-match or
    DIRECT-accuracy metric.  A candidate counts when it has the same source
    video and overlaps at least ``overlap_ratio`` of the expected interval.
    """
    if not expected:
        return 1.0
    if k <= 0:
        return 0.0
    hits = 0
    for target in expected:
        target_duration = max(1, target.end_ms - target.start_ms)
        found = any(
            candidate.video_id == target.video_id
            and max(0, min(candidate.end_ms, target.end_ms)
                    - max(candidate.start_ms, target.start_ms)) / target_duration >= overlap_ratio
            for candidate in candidates[:k]
        )
        hits += int(found)
    return hits / len(expected)

"""Default pacing for explanatory edits, independent of subject, file or model.

Directors' rule: a regular independent shot lasts at least 3 seconds; the
median target is 5-7 seconds; the 1.5-3s range is reserved for genuinely short
S-tier action evidence (handled at the director layer, not here).
"""

from math import ceil

MIN_SHOT_MS = 3000
TARGET_SHOT_MS = 5500
MAX_SHOT_MS = 8000


def preferred_shot_counts(
    total_ms: int, candidate_count: int, *, minimum_ms: int = MIN_SHOT_MS,
    maximum_ms: int = MAX_SHOT_MS,
) -> list[int]:
    if total_ms <= 0:
        return []
    minimum = min(max(1, minimum_ms), total_ms)
    maximum = max(minimum, maximum_ms)
    counts = range(ceil(total_ms / maximum), min(candidate_count, total_ms // minimum) + 1)
    return sorted(counts, key=lambda count: (abs(total_ms / count - TARGET_SHOT_MS), count))


def allocate_durations(
    total_ms: int, capacities: list[int], *, minimum_ms: int = MIN_SHOT_MS,
    maximum_ms: int = MAX_SHOT_MS,
) -> list[int] | None:
    """Balance a whole content window before cutting; do not append a tiny remainder."""
    if total_ms <= 0 or not capacities:
        return None
    minimum = min(max(1, minimum_ms), total_ms)
    capacities = [min(maximum_ms, capacity) for capacity in capacities]
    count = len(capacities)
    if any(capacity < minimum for capacity in capacities):
        return None
    if count * minimum > total_ms or sum(capacities) < total_ms:
        return None
    durations = [min(capacity, total_ms // count) for capacity in capacities]
    remaining = total_ms - sum(durations)
    while remaining:
        open_slots = [i for i, duration in enumerate(durations) if duration < capacities[i]]
        share = max(1, remaining // len(open_slots))
        for index in open_slots:
            amount = min(share, remaining, capacities[index] - durations[index])
            durations[index] += amount
            remaining -= amount
    return durations


def has_pacing_capacity(total_ms: int, capacities: list[int], *, minimum_ms: int = MIN_SHOT_MS) -> bool:
    """Accepted candidates are disjoint; enough raw milliseconds alone are not sufficient."""
    largest = sorted(capacities, reverse=True)
    return any(allocate_durations(total_ms, largest[:count], minimum_ms=minimum_ms) is not None
               for count in preferred_shot_counts(total_ms, len(largest), minimum_ms=minimum_ms))


def review_windows(start_ms: int, end_ms: int, minimum_ms: int) -> list[tuple[int, int]]:
    """Partition a continuous eligible source range without producing a sliver at its end."""
    duration = end_ms - start_ms
    if duration < minimum_ms:
        return []
    count = ceil(duration / MAX_SHOT_MS)
    return [(start_ms + duration * i // count, start_ms + duration * (i + 1) // count)
            for i in range(count)
            if duration * (i + 1) // count - duration * i // count >= minimum_ms]

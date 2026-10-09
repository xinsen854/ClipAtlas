"""Deterministic first-pass batch assignment over prepared single-entry plans.

Batch planning protects scarce S/direct evidence first and then uses a rolling
source-range cooldown.  This remains deterministic: the batch allocator never
turns a weak semantic match into DIRECT evidence and never bypasses media
admission.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from clipatlas.roughcut.models import RoughCutPlan


def batch_assignment_order(plans: Sequence[RoughCutPlan]) -> list[int]:
    """Protect scarce S/direct evidence before common connective footage."""
    rows: list[tuple[int, int, int, int]] = []
    for index, plan in enumerate(plans):
        s_beats = [beat for beat in plan.beats if beat.retrieval_intent.get("director_importance") == "S"]
        direct = [clip for clip in plan.clips if clip.director_fit == "DIRECT"]
        candidate_ids = {
            str(item.get("candidate_id"))
            for beat in plan.beats
            for item in (beat.retrieval_intent.get("candidate_matrix") or [])
            if isinstance(item, dict) and item.get("candidate_id")
        }
        # Fewer independent candidates means higher allocation priority.
        rows.append((len(candidate_ids), -len(direct), -len(s_beats), index))
    return [index for *_, index in sorted(rows)]


def append_plan_usage(
    usage: dict[str, list[tuple[int, int, int]]],
    plan: RoughCutPlan,
    *,
    batch_index: int,
) -> None:
    """Record unique source ranges used by one output.

    Exact duplicate/overlapping ranges inside the same plan are collapsed for
    batch accounting.  The planner itself is still responsible for preventing
    same-output overlap; this keeps the cross-output cooldown from double
    charging one accidental duplicate.
    """
    per_video: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for clip in plan.clips:
        key = str(clip.video_id)
        start, end = clip.source_in_ms, clip.source_out_ms
        if any(start < used_end and end > used_start for used_start, used_end in per_video[key]):
            continue
        per_video[key].append((start, end))
        usage.setdefault(key, []).append((start, end, batch_index))


def batch_usage_from_plans(plans: Sequence[RoughCutPlan]) -> dict[str, list[tuple[int, int, int]]]:
    usage: dict[str, list[tuple[int, int, int]]] = defaultdict(list)
    for index, plan in enumerate(plans):
        append_plan_usage(usage, plan, batch_index=index)
    return dict(usage)

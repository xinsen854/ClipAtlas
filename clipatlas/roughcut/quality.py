"""Reproducible plan metrics, separate from human visual accuracy."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic import BaseModel, Field
from clipatlas.domain.evidence import ClaimMatch

if TYPE_CHECKING:
    from clipatlas.roughcut.models import RoughCutClip, ScriptBeat


class ClipQuality(BaseModel):
    index: int
    beat_id: UUID
    video_id: UUID
    source_in_ms: int
    source_out_ms: int
    timeline_in_ms: int
    timeline_out_ms: int
    director_fit: str | None
    schedule_level: str
    evidence_retained: bool | None
    missing_requirements: list[str]
    repeated_source_ms: int
    batch_repeated_source_ms: int
    pollution_level: str | None
    issues: list[str]
    claim_matches: list[ClaimMatch] = Field(default_factory=list)


class BeatQuality(BaseModel):
    beat_id: UUID
    sequence: int
    importance: str | None
    clip_count: int
    covered_ms: int
    direct_ms: int
    target_ms: int


class QualityReport(BaseModel):
    version: int = 2
    claim_counts: dict[str, int] = Field(default_factory=dict)
    status: Literal["needs_review"] = "needs_review"
    timeline_coverage: float
    auto_direct_duration_ratio: float
    auto_s_direct_duration_ratio: float | None
    auto_s_claim_direct_ratio: float | None = None
    auto_effective_claim_ratio: float | None = None
    human_s_accuracy: float | None = None
    human_effective_accuracy: float | None = None
    human_reviewed_clips: int = 0
    accuracy_targets_verified: bool = False
    one_shot_beat_ratio: float
    short_clip_count: int
    repeated_source_ms: int
    batch_repeated_source_ms: int
    pollution_counts: dict[str, int]
    schedule_counts: dict[str, int]
    video_duration_ms: dict[str, int]
    max_video_duration_share: float
    source_return_count: int
    clips: list[ClipQuality]
    beats: list[BeatQuality]
    limitations: list[str] = Field(default_factory=lambda: [
        "Automatic annotation checks are not human visual accuracy.",
        "Human S accuracy (85%) and effective accuracy (80%) have not been measured.",
        "Pollution and evidence checks depend on catalog annotation completeness.",
        "Vertical composition and installed-editor rendering have not been verified.",
    ])


def _union_duration(ranges: list[tuple[int, int]]) -> int:
    end = -1
    duration = 0
    for start, stop in sorted(ranges):
        duration += max(0, stop - max(start, end))
        end = max(end, stop)
    return duration


def _overlap_ms(start: int, end: int, ranges: list[tuple[int, int]]) -> int:
    return _union_duration([(max(start, a), min(end, b)) for a, b in ranges
                            if a < end and b > start])


def build_quality_report(
    clips: list[RoughCutClip], beats: list[ScriptBeat], total_ms: int,
    batch_usage: dict[str, list[tuple[int, int, int]]] | None = None,
) -> QualityReport:
    from clipatlas.roughcut.evidence import anchor_retained

    rows = []
    prior: dict[UUID, list[tuple[int, int]]] = defaultdict(list)
    video_duration: dict[str, int] = defaultdict(int)
    source_returns = 0
    previous_video = None
    for index, clip in enumerate(clips):
        retained = anchor_retained(clip)
        repeat = _overlap_ms(clip.source_in_ms, clip.source_out_ms, prior[clip.video_id])
        batch_repeat = _overlap_ms(clip.source_in_ms, clip.source_out_ms, [
            (a, b) for a, b, _ in (batch_usage or {}).get(str(clip.video_id), [])
        ])
        issues = list(clip.evidence_check_reasons)
        if retained is False:
            issues.append("evidence_anchor_not_retained")
        if repeat:
            issues.append("repeated_source")
        if batch_repeat:
            issues.append("batch_repeated_source")
        if clip.director_fit is None:
            issues.append("no_director_verdict")
        if clip.safe_in_ms is not None and clip.source_in_ms < clip.safe_in_ms:
            issues.append("outside_safe_range")
        if clip.safe_out_ms is not None and clip.source_out_ms > clip.safe_out_ms:
            issues.append("outside_safe_range")
        if prior[clip.video_id] and previous_video != clip.video_id:
            source_returns += 1
        previous_video = clip.video_id
        prior[clip.video_id].append((clip.source_in_ms, clip.source_out_ms))
        video_duration[str(clip.video_id)] += clip.timeline_out_ms - clip.timeline_in_ms
        rows.append(ClipQuality(
            index=index, beat_id=clip.beat_id, video_id=clip.video_id,
            source_in_ms=clip.source_in_ms, source_out_ms=clip.source_out_ms,
            timeline_in_ms=clip.timeline_in_ms, timeline_out_ms=clip.timeline_out_ms,
            director_fit=clip.director_fit, schedule_level=clip.schedule_level,
            evidence_retained=retained,
            missing_requirements=clip.director_missing_requirements,
            repeated_source_ms=repeat, batch_repeated_source_ms=batch_repeat,
            pollution_level=clip.pollution_level, issues=list(dict.fromkeys(issues)),
            claim_matches=clip.claim_matches,
        ))
    direct = [clip for clip in clips if clip.director_fit == "DIRECT"
              and clip.schedule_level == "exact"
              and (anchor_retained(clip) is not False or bool(clip.claim_matches))]
    beat_rows = []
    for beat in beats:
        intersecting = [clip for clip in clips if clip.timeline_in_ms < beat.timeline_end_ms
                        and clip.timeline_out_ms > beat.timeline_start_ms]
        start, end = beat.timeline_start_ms, beat.timeline_end_ms
        beat_rows.append(BeatQuality(
            beat_id=beat.id, sequence=beat.sequence,
            importance=beat.retrieval_intent.get("director_importance"),
            clip_count=len(intersecting), target_ms=beat.target_duration_ms,
            covered_ms=_overlap_ms(start, end, [(c.timeline_in_ms, c.timeline_out_ms)
                                              for c in intersecting]),
            direct_ms=_overlap_ms(start, end, [(c.timeline_in_ms, c.timeline_out_ms)
                                             for c in direct]),
        ))
    s_rows = [row for row in beat_rows if row.importance == "S"]
    s_duration = sum(row.target_ms for row in s_rows)
    claim_best = {}
    claim_rank = {"REJECT": 0, "UNKNOWN": 1, "SUPPORT": 2, "DIRECT": 3}
    for clip in clips:
        for match in clip.claim_matches:
            key = (match.claim_id, match.source_quote, match.importance)
            if key not in claim_best or claim_rank[match.level] > claim_rank[claim_best[key].level]:
                claim_best[key] = match
    evaluated_claims = [match for match in claim_best.values() if match.importance in {"S", "A"}]
    s_claims = [match for match in evaluated_claims if match.importance == "S"]
    return QualityReport(
        claim_counts=dict(Counter(match.level for match in claim_best.values())),
        timeline_coverage=_overlap_ms(0, total_ms, [(c.timeline_in_ms, c.timeline_out_ms)
                                                  for c in clips]) / total_ms,
        auto_direct_duration_ratio=_overlap_ms(0, total_ms, [
            (c.timeline_in_ms, c.timeline_out_ms) for c in direct]) / total_ms,
        auto_s_direct_duration_ratio=(sum(r.direct_ms for r in s_rows) / s_duration
                                      if s_duration else None),
        auto_s_claim_direct_ratio=(
            sum(match.level == "DIRECT" for match in s_claims) / len(s_claims)
            if s_claims else None
        ),
        auto_effective_claim_ratio=(
            sum(match.level in {"DIRECT", "SUPPORT"} for match in evaluated_claims)
            / len(evaluated_claims) if evaluated_claims else None
        ),
        one_shot_beat_ratio=(sum(r.clip_count == 1 for r in beat_rows) / len(beat_rows)
                             if beat_rows else 0),
        short_clip_count=sum(c.timeline_out_ms - c.timeline_in_ms < 3000 for c in clips),
        repeated_source_ms=sum(row.repeated_source_ms for row in rows),
        batch_repeated_source_ms=sum(row.batch_repeated_source_ms for row in rows),
        pollution_counts=dict(Counter(c.pollution_level or "unknown" for c in clips)),
        schedule_counts=dict(Counter(c.schedule_level for c in clips)),
        video_duration_ms=dict(video_duration),
        max_video_duration_share=max(video_duration.values(), default=0) / total_ms,
        source_return_count=source_returns, clips=rows, beats=beat_rows,
    )

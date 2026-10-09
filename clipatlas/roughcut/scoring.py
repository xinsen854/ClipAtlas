import re
from collections.abc import Iterable
from typing import Any

from clipatlas.roughcut.contracts import RoughCutSearchHit
from clipatlas.roughcut.models import (
    CandidateScore,
    PlannerSettings,
    RoughCutClip,
    ScriptBeat,
)

_LATIN_TOKEN_RE = re.compile(r"[a-z0-9]+")
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")

# 数字+紧邻单位的规范化 token：200W/200万→200万；86%/86％→86%；12个月→12个月。
_NUMBER_UNIT_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*"
    r"(万亿|亿|千万|百万|万|W|w|％|%|倍|个月|月|年|天|元|公里|千米|米|秒|分钟|分|小时|台|辆|人|家|款|档|L2\.?\d*)?"
)
_UNIT_NORMALIZE = {"W": "万", "w": "万", "％": "%"}


def extract_number_tokens(text: str) -> set[str]:
    """Extract numeric claims (with their units) from narration or candidate text.

    Numbers matter most in S/A-tier claims (200万用户、86%、12个月、L2.5)，而画面
    OCR/ASR 提取出的同样数字是“画面确实讲了这个数字”的强证据。这里只做本地
    字符串级匹配，不调用任何 API。
    """
    tokens: set[str] = set()
    for match in _NUMBER_UNIT_RE.finditer(text):
        number = match.group(1)
        if number is None:
            continue
        unit = (match.group(2) or "").strip()
        unit = _UNIT_NORMALIZE.get(unit, unit)
        tokens.add(f"{number}{unit}" if unit else number)
    return tokens


def extract_features(text: str) -> set[str]:
    normalized = text.lower()
    features = set(_LATIN_TOKEN_RE.findall(normalized))

    for run in _CJK_RUN_RE.findall(normalized):
        features.update(run)
        features.update(run[index : index + 2] for index in range(len(run) - 1))

    return features


def overlap_score(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


def _features_from_values(values: Iterable[str]) -> set[str]:
    features: set[str] = set()
    for value in values:
        features.update(extract_features(value))
    return features


def batch_occupancy_for(
    hit: RoughCutSearchHit,
    usage: dict[str, list[tuple[int, int, int]]] | None,
    *,
    current_index: int,
    gap: int,
    min_overlap_ms: int = 1000,
) -> int:
    """Count how many other drafts of the same batch (that are still within the
    rolling release window) occupy this candidate's source window.

    usage maps video_id -> [(start_ms, end_ms, last_used_batch_index)].
    A used range is treated as *released* once current_index - last_used_batch_index
    >= gap, so scarce S-tier footage naturally gets reused every few drafts.
    """
    if not usage:
        return 0
    ranges = usage.get(str(hit.video_id))
    if not ranges:
        return 0
    start, end = hit.source_start_ms, hit.source_end_ms
    overlaps = 0
    for used_start, used_end, used_index in ranges:
        if current_index - used_index < gap:
            overlap = min(end, used_end) - max(start, used_start)
            if overlap >= min_overlap_ms:
                overlaps += 1
    return overlaps


class CandidateScorer:
    def __init__(self, settings: PlannerSettings | None = None) -> None:
        self._settings = settings or PlannerSettings()

    def score(
        self,
        beat: ScriptBeat,
        hit: RoughCutSearchHit,
        *,
        needed_duration_ms: int,
        prior_use_count: int = 0,
        previous_clip: RoughCutClip | None = None,
    ) -> CandidateScore:
        beat_features = extract_features(beat.query_text)
        annotation = hit.annotation

        semantic_score = min(1.0, max(0.0, hit.score))
        action_score = overlap_score(
            beat_features,
            _features_from_values(annotation.actions),
        )
        scene_score = overlap_score(
            beat_features,
            _features_from_values(annotation.scene),
        )
        emotion_score = overlap_score(
            beat_features,
            _features_from_values(annotation.emotions),
        )

        candidate_duration_ms = max(0, hit.source_end_ms - hit.source_start_ms)
        if candidate_duration_ms <= 0 or needed_duration_ms <= 0:
            duration_fit_score = 0.0
        else:
            duration_fit_score = min(candidate_duration_ms, needed_duration_ms) / max(
                candidate_duration_ms,
                needed_duration_ms,
            )

        quality_score = annotation.confidence if annotation.confidence is not None else 0.5
        if annotation.verified:
            quality_score = min(1.0, quality_score + 0.10)

        numeric_score = self._numeric_score(beat, hit)

        continuity_bonus = self._continuity_bonus(hit, previous_clip)
        reuse_penalty = min(
            self._settings.max_reuse_penalty,
            self._settings.reuse_penalty_per_use * max(0, prior_use_count),
        )

        total_score = (
            self._settings.semantic_weight * semantic_score
            + self._settings.action_weight * action_score
            + self._settings.scene_weight * scene_score
            + self._settings.emotion_weight * emotion_score
            + self._settings.duration_weight * duration_fit_score
            + self._settings.quality_weight * quality_score
            + self._settings.numeric_weight * numeric_score
            + continuity_bonus
            - reuse_penalty
        )

        return CandidateScore(
            segment_id=hit.segment_id,
            semantic_score=semantic_score,
            action_score=action_score,
            scene_score=scene_score,
            emotion_score=emotion_score,
            duration_fit_score=duration_fit_score,
            quality_score=quality_score,
            numeric_score=numeric_score,
            continuity_bonus=continuity_bonus,
            reuse_penalty=reuse_penalty,
            total_score=total_score,
        )

    def _numeric_score(self, beat: ScriptBeat, hit: RoughCutSearchHit) -> float:
        """S/A 级重点文案里明确的数字，尽量匹配画面提取出的同一数字。"""
        beat_numbers = extract_number_tokens(beat.query_text)
        if not beat_numbers:
            return 0.0
        annotation = hit.annotation
        candidate_parts = [
            *getattr(hit, "asr_texts", []),
            *getattr(hit, "ocr_texts", []),
            *annotation.ocr,
            annotation.description,
            *annotation.objects,
            *annotation.actions,
            *annotation.characters,
            *annotation.scene,
        ]
        hit_numbers = extract_number_tokens(" ".join(part or "" for part in candidate_parts))
        if not hit_numbers:
            return 0.0
        matched = len(beat_numbers & hit_numbers)
        if matched <= 0:
            return 0.0
        importance = (beat.retrieval_intent or {}).get("director_importance")
        boost = self._settings.numeric_importance_boost if importance == "S" else 1.0
        return min(1.0, (matched / len(beat_numbers)) * boost)

    def _continuity_bonus(
        self,
        hit: RoughCutSearchHit,
        previous_clip: RoughCutClip | None,
    ) -> float:
        if previous_clip is None or previous_clip.video_id != hit.video_id:
            return 0.0

        if (
            hit.source_start_ms < previous_clip.source_out_ms
            and hit.source_end_ms > previous_clip.source_in_ms
        ):
            return 0.0

        if hit.source_start_ms >= previous_clip.source_out_ms:
            distance_ms = hit.source_start_ms - previous_clip.source_out_ms
        else:
            distance_ms = previous_clip.source_in_ms - hit.source_end_ms

        if distance_ms > self._settings.continuity_window_ms:
            return 0.0

        proximity = 1.0 - (distance_ms / self._settings.continuity_window_ms)
        return self._settings.max_continuity_bonus * max(0.0, proximity)

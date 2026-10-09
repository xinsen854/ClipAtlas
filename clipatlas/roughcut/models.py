from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator

from clipatlas.domain.models import utc_now
from clipatlas.roughcut.quality import QualityReport
from clipatlas.domain.evidence import ClaimMatch


class PlannerSettings(BaseModel):
    top_k: int = Field(default=12, ge=1, le=100)
    semantic_weight: float = Field(default=0.58, ge=0.0)
    action_weight: float = Field(default=0.08, ge=0.0)
    scene_weight: float = Field(default=0.08, ge=0.0)
    emotion_weight: float = Field(default=0.06, ge=0.0)
    duration_weight: float = Field(default=0.12, ge=0.0)
    quality_weight: float = Field(default=0.05, ge=0.0)
    # S/A 级重点文案中明确的数字（200万、12个月、86% 等）应与画面 OCR/ASR
    # 提取出的数字尽量对上；该权重只在文案含数字时参与。
    numeric_weight: float = Field(default=0.12, ge=0.0)
    # S 级重点的数字命中按此倍率加权，普通句子为 1.0。
    numeric_importance_boost: float = Field(default=1.5, ge=1.0)
    # 批次级去重：同一批次 20 条成片之间，尽量不重复使用同一段素材。
    # 占用采用“滚动释放”：片段被某条成片用过后，接下来 batch_reuse_gap 条
    # 内避让（优先换非占用画面）；超过间隔即视为已释放，可再次使用。
    # S 级 DIRECT 稀缺画面轻避让：间隔内也尽量换，换不到仍允许复用。
    batch_reuse_gap: int = Field(default=5, ge=1)
    batch_reuse_penalty_per_use: float = Field(default=0.45, ge=0.0)
    batch_reuse_direct_penalty_scale: float = Field(default=0.3, ge=0.0, le=1.0)
    batch_video_penalty_per_use: float = Field(default=0.18, ge=0.0)
    max_video_timeline_share: float = Field(default=0.35, ge=0.1, le=1.0)
    max_continuity_bonus: float = Field(default=0.03, ge=0.0)
    continuity_window_ms: int = Field(default=30_000, gt=0)
    reuse_penalty_per_use: float = Field(default=0.08, ge=0.0)
    max_reuse_penalty: float = Field(default=0.20, ge=0.0)


class ScriptBeat(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    narration_track_id: UUID
    sequence: int = Field(ge=0)
    kind: Literal["narration", "visual_only"] = "narration"
    text: str = ""
    timeline_start_ms: int = Field(ge=0)
    timeline_end_ms: int = Field(gt=0)
    target_duration_ms: int = Field(gt=0)
    query_text: str = Field(min_length=1)
    retrieval_intent: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_timeline_window(self) -> "ScriptBeat":
        if self.kind == "narration" and not self.text.strip():
            raise ValueError("narration beat text must not be empty")
        if self.timeline_end_ms <= self.timeline_start_ms:
            raise ValueError("timeline_end_ms must be greater than timeline_start_ms")
        if self.target_duration_ms != self.timeline_end_ms - self.timeline_start_ms:
            raise ValueError("target_duration_ms must match the timeline window")
        return self


class CandidateScore(BaseModel):
    segment_id: UUID
    semantic_score: float = Field(ge=0.0, le=1.0)
    action_score: float = Field(ge=0.0, le=1.0)
    scene_score: float = Field(ge=0.0, le=1.0)
    emotion_score: float = Field(ge=0.0, le=1.0)
    duration_fit_score: float = Field(ge=0.0, le=1.0)
    quality_score: float = Field(ge=0.0, le=1.0)
    numeric_score: float = Field(default=0.0, ge=0.0, le=1.0)
    continuity_bonus: float = Field(ge=0.0)
    reuse_penalty: float = Field(ge=0.0)
    total_score: float


class RoughCutClip(BaseModel):
    beat_id: UUID
    segment_id: UUID
    video_id: UUID
    source_uri: str = Field(min_length=1)
    source_in_ms: int = Field(ge=0)
    source_out_ms: int = Field(gt=0)
    anchor_in_ms: int | None = Field(default=None, ge=0)
    anchor_out_ms: int | None = Field(default=None, gt=0)
    safe_in_ms: int | None = Field(default=None, ge=0)
    safe_out_ms: int | None = Field(default=None, gt=0)
    continuity_key: str | None = None
    visual_family: str | None = None
    presentation_type: str | None = None
    pollution_level: str | None = None
    protocol_candidate_type: str | None = None
    protocol_id: UUID | None = None
    continuity_status: str | None = None
    match_level: str | None = None
    director_fit: str | None = None
    director_matched_requirements: list[str] = Field(default_factory=list)
    director_missing_requirements: list[str] = Field(default_factory=list)
    evidence_retained: bool | None = None
    evidence_check_reasons: list[str] = Field(default_factory=list)
    claim_matches: list[ClaimMatch] = Field(default_factory=list)
    timeline_in_ms: int = Field(ge=0)
    timeline_out_ms: int = Field(gt=0)
    score: float
    score_breakdown: CandidateScore
    selection_reason: str = Field(min_length=1)
    schedule_level: str = "exact"

    @model_validator(mode="after")
    def validate_clip_windows(self) -> "RoughCutClip":
        if self.source_out_ms <= self.source_in_ms:
            raise ValueError("source_out_ms must be greater than source_in_ms")
        if self.timeline_out_ms <= self.timeline_in_ms:
            raise ValueError("timeline_out_ms must be greater than timeline_in_ms")
        source_duration = self.source_out_ms - self.source_in_ms
        timeline_duration = self.timeline_out_ms - self.timeline_in_ms
        if source_duration != timeline_duration:
            raise ValueError("source and timeline durations must match")
        return self


class RoughCutSubtitle(BaseModel):
    """One on-screen subtitle line aligned to a narration beat.

    ``text`` is the rule-projected subtitle text (``subtitle_replace`` applied),
    so wording that must not appear on screen (e.g. broadcast-norm restricted
    terms) is already removed while the narration audio still speaks it.
    """

    text: str = Field(min_length=1)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_window(self) -> "RoughCutSubtitle":
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        return self


class RoughCutPlan(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    narration_track_id: UUID
    narration_revision: int = Field(ge=1)
    revision: int = Field(ge=1)
    total_duration_ms: int = Field(gt=0)
    settings: PlannerSettings
    beats: list[ScriptBeat]
    clips: list[RoughCutClip]
    subtitles: list[RoughCutSubtitle] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    quality_report: QualityReport | None = None
    story_provenance: dict[str, object] | None = None
    protocol_version: str = "legacy-roughcut-v1"
    retrieval_protocol_version: str = "legacy-visual-retrieval-v1"
    created_at: datetime = Field(default_factory=utc_now)

"""Candidate matrix for single-script planning.

The matrix is a persisted-in-plan recall snapshot. It is intentionally not a
final verdict: local evidence rules still decide whether a selected clip is
DIRECT, SUPPORT or UNKNOWN. The row nevertheless carries enough stable
metadata for API reranking and global assignment without re-reading video.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from clipatlas.domain.visual_protocol import ScriptVisualRequirement, normalize_match_level
from clipatlas.retrieval.text_normalization import matched_terms


class CandidateMatrixRow(BaseModel):
    requirement_id: str
    sentence_id: str | None = None
    source_quote: str | None = None
    importance: str | None = None
    candidate_type: str = "legacy"
    candidate_id: UUID | None = None
    video_id: UUID
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    anchor_start_ms: int | None = Field(default=None, ge=0)
    anchor_end_ms: int | None = Field(default=None, ge=0)
    continuity_status: str | None = None
    match_level: str | None = None
    pollution_level: str | None = None
    visual_family: str | None = None
    presentation_type: str | None = None
    subject_score: float = Field(default=0.0, ge=0.0, le=1.0)
    action_score: float = Field(default=0.0, ge=0.0, le=1.0)
    scene_score: float = Field(default=0.0, ge=0.0, le=1.0)
    environment_score: float = Field(default=0.0, ge=0.0, le=1.0)
    object_score: float = Field(default=0.0, ge=0.0, le=1.0)
    configuration_score: float = Field(default=0.0, ge=0.0, le=1.0)
    quantity_score: float = Field(default=0.0, ge=0.0, le=1.0)
    relation_score: float = Field(default=0.0, ge=0.0, le=1.0)
    order_score: float = Field(default=0.0, ge=0.0, le=1.0)
    vector_score: float = Field(default=0.0, ge=0.0)
    preliminary_level: str = "candidate"


def _score(required: list[str], evidence: list[str]) -> float:
    wanted = list(dict.fromkeys(value.strip() for value in required if value.strip()))
    if not wanted:
        return 0.0
    return len(matched_terms(" ".join(evidence), wanted)) / len(wanted)


def _evidence(hit: Any) -> dict[str, list[str]]:
    annotation = hit.annotation
    propositions = [
        fact.statement.proposition
        for fact in annotation.facts
        if fact.statement is not None
    ]
    scenes = [
        *annotation.scene,
        *(item.value for item in propositions if item.predicate == "scene"),
    ]
    return {
        "subjects": [
            *annotation.characters,
            *(item.subject for item in propositions),
            *(item.value for item in propositions if item.predicate == "identity"),
        ],
        "actions": [
            *annotation.actions,
            *(item.value for item in propositions if item.predicate == "action"),
        ],
        "scenes": scenes,
        # SemanticAnnotation has one scene channel. Timeline-protocol events
        # project environment/road context into it, so this is intentionally
        # the same evidence channel rather than an invented duplicate truth.
        "environments": scenes,
        "objects": [
            *annotation.objects,
            *(item.value for item in propositions if item.predicate == "presence"),
        ],
        "configurations": [
            item.value for item in propositions if item.predicate == "configuration"
        ],
        "quantities": [
            " ".join(str(value) for value in (item.value, item.unit, item.scope) if value)
            for item in propositions if item.predicate == "quantity"
        ] + list(annotation.ocr),
        "relations": [
            item.value for item in propositions if item.predicate == "relation"
        ],
    }


def _row(requirement: ScriptVisualRequirement, hit: Any) -> CandidateMatrixRow:
    evidence = _evidence(hit)
    subject_score = _score([requirement.subject] if requirement.subject else [], evidence["subjects"])
    action_score = _score(
        [*([requirement.action] if requirement.action else []), *requirement.state_changes],
        evidence["actions"],
    )
    scene_score = _score([requirement.scene] if requirement.scene else [], evidence["scenes"])
    environment_score = _score(
        [requirement.environment] if requirement.environment else [],
        evidence["environments"],
    )
    object_score = _score(requirement.objects, evidence["objects"])
    configuration_score = _score(requirement.configurations, evidence["configurations"])
    quantity_score = _score(requirement.quantities, evidence["quantities"])
    relation_score = _score(requirement.relations, evidence["relations"])
    continuity = getattr(hit, "continuity_status", None)
    order_score = 0.0
    if requirement.temporal_relation:
        if getattr(hit, "protocol_candidate_type", None) == "window":
            order_score = 1.0 if continuity == "confirmed_continuity" else (
                0.6 if continuity == "probable_continuity" else 0.0
            )
    component_scores = [
        score for needed, score in (
            (requirement.subject is not None, subject_score),
            (requirement.action is not None, action_score),
            (requirement.scene is not None, scene_score),
            (requirement.environment is not None, environment_score),
            (bool(requirement.objects), object_score),
            (bool(requirement.configurations), configuration_score),
            (bool(requirement.quantities), quantity_score),
            (bool(requirement.relations), relation_score),
            (requirement.temporal_relation is not None, order_score),
        ) if needed
    ]
    preliminary = (
        "strong_candidate" if component_scores and all(score >= 0.99 for score in component_scores)
        else "related_candidate" if any(score > 0 for score in component_scores)
        else "unmatched_candidate"
    )
    return CandidateMatrixRow(
        requirement_id=requirement.id,
        sentence_id=requirement.sentence_id,
        source_quote=requirement.source_quote,
        importance=requirement.importance,
        candidate_type=str(getattr(hit, "protocol_candidate_type", None) or "legacy"),
        candidate_id=getattr(hit, "protocol_id", None),
        video_id=hit.video_id,
        start_ms=hit.source_start_ms,
        end_ms=hit.source_end_ms,
        anchor_start_ms=getattr(hit, "anchor_start_ms", None),
        anchor_end_ms=getattr(hit, "anchor_end_ms", None),
        continuity_status=continuity,
        match_level=getattr(hit, "match_level", None) or normalize_match_level(
            getattr(hit, "schedule_level", None)
        ),
        pollution_level=getattr(hit, "pollution_level", None),
        visual_family=getattr(hit, "visual_family", None),
        presentation_type=getattr(hit, "presentation_type", None),
        subject_score=subject_score,
        action_score=action_score,
        scene_score=scene_score,
        environment_score=environment_score,
        object_score=object_score,
        configuration_score=configuration_score,
        quantity_score=quantity_score,
        relation_score=relation_score,
        order_score=order_score,
        vector_score=float(
            getattr(hit, "hybrid_score", 0.0) or getattr(hit, "score", 0.0) or 0.0
        ),
        preliminary_level=preliminary,
    )


def build_candidate_matrix(beat: Any, hits: list[Any]) -> list[CandidateMatrixRow]:
    requirements = (beat.retrieval_intent or {}).get("visual_requirements") or []
    parsed = []
    for item in requirements:
        try:
            parsed.append(ScriptVisualRequirement.model_validate(item))
        except (TypeError, ValueError):
            continue
    rows: list[CandidateMatrixRow] = []
    if not parsed:
        for hit in hits:
            rows.append(CandidateMatrixRow(
                requirement_id=f"beat:{beat.id}",
                candidate_type=str(getattr(hit, "protocol_candidate_type", None) or "legacy"),
                candidate_id=getattr(hit, "protocol_id", None),
                video_id=hit.video_id,
                start_ms=hit.source_start_ms,
                end_ms=hit.source_end_ms,
                anchor_start_ms=getattr(hit, "anchor_start_ms", None),
                anchor_end_ms=getattr(hit, "anchor_end_ms", None),
                continuity_status=getattr(hit, "continuity_status", None),
                match_level=getattr(hit, "match_level", None) or normalize_match_level(
                    getattr(hit, "schedule_level", None)
                ),
                pollution_level=getattr(hit, "pollution_level", None),
                visual_family=getattr(hit, "visual_family", None),
                presentation_type=getattr(hit, "presentation_type", None),
                vector_score=float(
                    getattr(hit, "hybrid_score", 0.0) or getattr(hit, "score", 0.0) or 0.0
                ),
                preliminary_level="unscored_candidate",
            ))
        return rows
    for hit in hits:
        rows.extend(_row(requirement, hit) for requirement in parsed)
    return rows

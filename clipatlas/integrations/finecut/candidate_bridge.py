from pydantic import ValidationError

from clipatlas.roughcut.candidate_matrix import CandidateMatrixRow
from clipatlas.roughcut.models import ScriptBeat
from finecut.models import CandidateItem, CandidateList

_DISPLAY_LEVELS = {
    "DIRECT": "S",
    "SUPPORT": "A",
    "RELATED": "B",
    "GENERIC": "Generic",
    "SOURCE": "Fallback/Source",
    "REUSE": "Fallback/Reuse",
}


def candidate_list_from_beat(beat: ScriptBeat) -> CandidateList:
    items: list[CandidateItem] = []
    raw_rows = (beat.retrieval_intent or {}).get("candidate_matrix") or []
    if not isinstance(raw_rows, list):
        return CandidateList(context_id=beat.id)

    for raw in raw_rows:
        try:
            row = CandidateMatrixRow.model_validate(raw)
        except (TypeError, ValidationError):
            continue
        display_level = _DISPLAY_LEVELS.get(row.match_level or "")
        if (
            display_level is None
            or row.pollution_level == "blocked"
            or row.end_ms <= row.start_ms
        ):
            continue
        items.append(
            CandidateItem(
                requirement_id=row.requirement_id,
                sentence_id=row.sentence_id,
                source_quote=row.source_quote,
                importance=row.importance,
                candidate_type=row.candidate_type,
                candidate_id=row.candidate_id,
                media_id=row.video_id,
                source_in_ms=row.start_ms,
                source_out_ms=row.end_ms,
                anchor_in_ms=row.anchor_start_ms,
                anchor_out_ms=row.anchor_end_ms,
                continuity_status=row.continuity_status,
                display_level=display_level,
                pollution_level=row.pollution_level,
                visual_family=row.visual_family,
                presentation_type=row.presentation_type,
                subject_score=row.subject_score,
                action_score=row.action_score,
                scene_score=row.scene_score,
                environment_score=row.environment_score,
                object_score=row.object_score,
                configuration_score=row.configuration_score,
                quantity_score=row.quantity_score,
                relation_score=row.relation_score,
                order_score=row.order_score,
                vector_score=row.vector_score,
                preliminary_level=row.preliminary_level,
            )
        )
    return CandidateList(context_id=beat.id, items=items)

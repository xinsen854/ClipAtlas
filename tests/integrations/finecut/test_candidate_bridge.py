from uuid import uuid4

from clipatlas.roughcut.models import ScriptBeat
from clipatlas.integrations.finecut.candidate_bridge import candidate_list_from_beat


def _row(
    *,
    match_level: str,
    importance: str = "A",
    pollution_level: str | None = "clean",
    start_ms: int = 1_000,
    end_ms: int = 4_000,
) -> dict[str, object]:
    return {
        "requirement_id": f"req-{match_level}",
        "sentence_id": "sentence-1",
        "source_quote": "测试文案",
        "importance": importance,
        "candidate_type": "window",
        "candidate_id": str(uuid4()),
        "video_id": str(uuid4()),
        "start_ms": start_ms,
        "end_ms": end_ms,
        "anchor_start_ms": 1_500,
        "anchor_end_ms": 2_500,
        "continuity_status": "confirmed_continuity",
        "match_level": match_level,
        "pollution_level": pollution_level,
        "visual_family": "vehicle-demo",
        "presentation_type": "wide",
        "subject_score": 0.9,
        "action_score": 0.8,
        "scene_score": 0.7,
        "environment_score": 0.6,
        "object_score": 0.5,
        "configuration_score": 0.4,
        "quantity_score": 0.3,
        "relation_score": 0.2,
        "order_score": 0.1,
        "vector_score": 0.75,
        "preliminary_level": "related_candidate",
    }


def _beat(rows: list[dict[str, object]]) -> ScriptBeat:
    return ScriptBeat(
        project_id=uuid4(),
        narration_track_id=uuid4(),
        sequence=0,
        text="测试文案",
        timeline_start_ms=0,
        timeline_end_ms=3_000,
        target_duration_ms=3_000,
        query_text="测试文案",
        retrieval_intent={"candidate_matrix": rows},
    )


def test_candidate_bridge_maps_levels_without_using_importance() -> None:
    beat = _beat([
        _row(match_level="DIRECT", importance="B"),
        _row(match_level="SUPPORT", importance="S"),
        _row(match_level="RELATED", importance="A"),
        _row(match_level="GENERIC", importance="B"),
        _row(match_level="SOURCE", importance="S"),
        _row(match_level="REUSE", importance="A"),
    ])

    result = candidate_list_from_beat(beat)

    assert result.context_id == beat.id
    assert [item.display_level for item in result.items] == [
        "S", "A", "B", "Generic", "Fallback/Source", "Fallback/Reuse",
    ]
    assert [item.importance for item in result.items] == ["B", "S", "A", "B", "S", "A"]


def test_candidate_bridge_filters_hidden_and_illegal_candidates() -> None:
    beat = _beat([
        _row(match_level="UNKNOWN"),
        _row(match_level="REJECT"),
        _row(match_level="DIRECT", pollution_level="blocked"),
        _row(match_level="DIRECT", start_ms=5_000, end_ms=4_000),
        _row(match_level="DIRECT"),
    ])

    result = candidate_list_from_beat(beat)

    assert len(result.items) == 1
    assert result.items[0].display_level == "S"


def test_candidate_bridge_preserves_existing_matrix_display_evidence() -> None:
    row = _row(match_level="DIRECT")
    beat = _beat([row])

    item = candidate_list_from_beat(beat).items[0]

    assert item.requirement_id == row["requirement_id"]
    assert item.sentence_id == row["sentence_id"]
    assert item.source_quote == row["source_quote"]
    assert str(item.media_id) == row["video_id"]
    assert item.source_in_ms == row["start_ms"]
    assert item.source_out_ms == row["end_ms"]
    assert item.anchor_in_ms == row["anchor_start_ms"]
    assert item.anchor_out_ms == row["anchor_end_ms"]
    assert item.continuity_status == row["continuity_status"]
    assert item.visual_family == row["visual_family"]
    assert item.presentation_type == row["presentation_type"]
    assert item.subject_score == row["subject_score"]
    assert item.action_score == row["action_score"]
    assert item.scene_score == row["scene_score"]
    assert item.environment_score == row["environment_score"]
    assert item.object_score == row["object_score"]
    assert item.configuration_score == row["configuration_score"]
    assert item.quantity_score == row["quantity_score"]
    assert item.relation_score == row["relation_score"]
    assert item.order_score == row["order_score"]
    assert item.vector_score == row["vector_score"]
    assert item.preliminary_level == row["preliminary_level"]

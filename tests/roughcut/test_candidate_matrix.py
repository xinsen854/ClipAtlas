from types import SimpleNamespace
from uuid import uuid4

from clipatlas.director.requirements import parse_script_visual_requirements
from clipatlas.domain.models import AnnotationOrigin, SemanticAnnotation
from clipatlas.roughcut.candidate_matrix import build_candidate_matrix


def test_candidate_matrix_keeps_window_identity_and_component_scores():
    video_id = uuid4()
    window_id = uuid4()
    requirement = parse_script_visual_requirements("泰钽700在山路爬坡。")[0]
    beat = SimpleNamespace(
        id=uuid4(),
        retrieval_intent={"visual_requirements": [requirement.model_dump(mode="json")]},
    )
    hit = SimpleNamespace(
        video_id=video_id, source_start_ms=1000, source_end_ms=7000,
        protocol_candidate_type="window", protocol_id=window_id,
        continuity_status="unknown_continuity",
        anchor_start_ms=2000, anchor_end_ms=5000,
        pollution_level="clean", visual_family="car-climb", presentation_type="wide",
        annotation=SemanticAnnotation(
            segment_id=uuid4(), origin=AnnotationOrigin.AI,
            description="泰钽700在山路爬坡", characters=["泰钽700"],
            actions=["爬坡"], scene=["山路"],
        ),
        hybrid_score=0.7, score=0.9, schedule_level="related",
    )
    rows = build_candidate_matrix(beat, [hit])
    assert len(rows) == 1
    assert rows[0].candidate_type == "window"
    assert rows[0].candidate_id == window_id
    assert rows[0].continuity_status == "unknown_continuity"
    assert rows[0].sentence_id == requirement.sentence_id
    assert rows[0].source_quote == requirement.source_quote
    assert rows[0].importance == requirement.importance
    assert rows[0].subject_score == 1.0
    assert rows[0].action_score == 1.0
    assert rows[0].scene_score == 1.0
    assert rows[0].environment_score == 1.0
    assert rows[0].anchor_start_ms == 2000
    assert rows[0].anchor_end_ms == 5000
    assert rows[0].pollution_level == "clean"
    assert rows[0].visual_family == "car-climb"
    assert rows[0].presentation_type == "wide"
    assert rows[0].order_score == 0.0
    assert rows[0].preliminary_level == "strong_candidate"

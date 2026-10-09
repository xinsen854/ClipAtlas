from dataclasses import dataclass
from uuid import UUID, uuid4

from clipatlas.domain.models import AnnotationOrigin, SemanticAnnotation
from clipatlas.roughcut.contracts import RoughCutSearchHit
from clipatlas.roughcut.models import ScriptBeat
from clipatlas.roughcut.scoring import CandidateScorer


@dataclass
class MinimalDeepHit:
    segment_id: UUID
    video_id: UUID
    source_uri: str
    source_start_ms: int
    source_end_ms: int
    score: float
    annotation: SemanticAnnotation


def test_candidate_scorer_accepts_structural_deep_pass_hit() -> None:
    project_id = uuid4()
    track_id = uuid4()
    segment_id = uuid4()
    video_id = uuid4()
    annotation = SemanticAnnotation(
        segment_id=segment_id,
        origin=AnnotationOrigin.AI,
        provider="qwen",
        model="qwen3.8-flash",
        description="车辆在越野路面行驶",
        actions=["行驶"],
        scene=["越野路面"],
        emotions=[],
        objects=["车辆"],
        confidence=0.9,
    )
    hit: RoughCutSearchHit = MinimalDeepHit(
        segment_id=segment_id,
        video_id=video_id,
        source_uri="file:///tmp/movie.mp4",
        source_start_ms=1_000,
        source_end_ms=6_000,
        score=0.8,
        annotation=annotation,
    )
    beat = ScriptBeat(
        project_id=project_id,
        narration_track_id=track_id,
        sequence=0,
        text="车辆在越野路面行驶",
        timeline_start_ms=0,
        timeline_end_ms=3_000,
        target_duration_ms=3_000,
        query_text="越野行驶",
    )

    score = CandidateScorer().score(
        beat,
        hit,
        needed_duration_ms=3_000,
    )

    assert score.segment_id == segment_id
    assert score.semantic_score == 0.8
    assert score.action_score > 0
    assert score.scene_score > 0

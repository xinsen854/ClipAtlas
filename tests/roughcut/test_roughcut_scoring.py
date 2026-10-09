from uuid import UUID, uuid4

import pytest

from clipatlas.domain.models import AnnotationOrigin, SemanticAnnotation
from clipatlas.retrieval.search import SemanticSearchHit
from clipatlas.roughcut.models import CandidateScore, RoughCutClip, ScriptBeat
from clipatlas.roughcut.scoring import CandidateScorer, extract_features, overlap_score


def _beat(*, text: str = "她推门进入仓库", duration_ms: int = 1000) -> ScriptBeat:
    return ScriptBeat(
        project_id=uuid4(),
        narration_track_id=uuid4(),
        sequence=0,
        text=text,
        timeline_start_ms=0,
        timeline_end_ms=duration_ms,
        target_duration_ms=duration_ms,
        query_text=text,
    )


def _hit(
    *,
    score: float = 0.8,
    segment_id: UUID | None = None,
    video_id: UUID | None = None,
    source_start_ms: int = 0,
    source_end_ms: int = 1000,
    actions: list[str] | None = None,
    scene: list[str] | None = None,
    emotions: list[str] | None = None,
    confidence: float | None = 0.5,
    verified: bool = False,
) -> SemanticSearchHit:
    resolved_segment_id = segment_id or uuid4()
    annotation = SemanticAnnotation(
        segment_id=resolved_segment_id,
        origin=AnnotationOrigin.AI,
        description="候选素材",
        actions=actions or [],
        scene=scene or [],
        emotions=emotions or [],
        confidence=confidence,
        verified=verified,
    )
    return SemanticSearchHit(
        segment_id=resolved_segment_id,
        video_id=video_id or uuid4(),
        source_uri="file:///source.mp4",
        source_start_ms=source_start_ms,
        source_end_ms=source_end_ms,
        score=score,
        effective_description=annotation.description,
        annotation=annotation,
        embedding_provider="test",
        embedding_model="test-model",
        embedding_dimensions=3,
    )


def _previous_clip(
    *,
    video_id: UUID,
    source_in_ms: int,
    source_out_ms: int,
) -> RoughCutClip:
    segment_id = uuid4()
    breakdown = CandidateScore(
        segment_id=segment_id,
        semantic_score=0.8,
        action_score=0.0,
        scene_score=0.0,
        emotion_score=0.0,
        duration_fit_score=1.0,
        quality_score=0.5,
        continuity_bonus=0.0,
        reuse_penalty=0.0,
        total_score=0.7,
    )
    return RoughCutClip(
        beat_id=uuid4(),
        segment_id=segment_id,
        video_id=video_id,
        source_uri="file:///source.mp4",
        source_in_ms=source_in_ms,
        source_out_ms=source_out_ms,
        timeline_in_ms=0,
        timeline_out_ms=source_out_ms - source_in_ms,
        score=breakdown.total_score,
        score_breakdown=breakdown,
        selection_reason="previous",
    )


def test_extract_features_supports_latin_words_cjk_chars_and_cjk_bigrams() -> None:
    features = extract_features("Door opens 仓库")

    assert {"door", "opens", "仓", "库", "仓库"}.issubset(features)


def test_overlap_score_uses_overlap_coefficient() -> None:
    assert overlap_score({"a", "b", "c"}, {"b", "c"}) == 1.0
    assert overlap_score(set(), {"b"}) == 0.0


def test_structured_action_signal_changes_rank_at_equal_semantic_similarity() -> None:
    beat = _beat()
    matching = _hit(score=0.8, actions=["推门"])
    unrelated = _hit(score=0.8, actions=["奔跑"])
    scorer = CandidateScorer()

    matching_score = scorer.score(beat, matching, needed_duration_ms=1000)
    unrelated_score = scorer.score(beat, unrelated, needed_duration_ms=1000)

    assert matching_score.action_score > unrelated_score.action_score
    assert matching_score.total_score > unrelated_score.total_score


@pytest.mark.parametrize(
    ("raw_score", "expected"),
    [(-0.4, 0.0), (0.4, 0.4), (1.4, 1.0)],
)
def test_semantic_score_is_clamped(raw_score: float, expected: float) -> None:
    result = CandidateScorer().score(
        _beat(),
        _hit(score=raw_score),
        needed_duration_ms=1000,
    )

    assert result.semantic_score == expected


def test_duration_fit_is_exact_ratio_against_needed_duration() -> None:
    scorer = CandidateScorer()
    exact = scorer.score(_beat(), _hit(source_end_ms=1000), needed_duration_ms=1000)
    short = scorer.score(_beat(), _hit(source_end_ms=500), needed_duration_ms=1000)

    assert exact.duration_fit_score == 1.0
    assert short.duration_fit_score == 0.5


def test_quality_uses_confidence_and_bounded_verified_bonus() -> None:
    scorer = CandidateScorer()
    verified = scorer.score(
        _beat(),
        _hit(confidence=0.95, verified=True),
        needed_duration_ms=1000,
    )
    defaulted = scorer.score(
        _beat(),
        _hit(confidence=None, verified=False),
        needed_duration_ms=1000,
    )

    assert verified.quality_score == 1.0
    assert defaulted.quality_score == 0.5


def test_nearby_non_overlapping_range_in_same_video_gets_continuity_bonus() -> None:
    video_id = uuid4()
    previous = _previous_clip(video_id=video_id, source_in_ms=0, source_out_ms=1000)
    candidate = _hit(
        video_id=video_id,
        source_start_ms=1500,
        source_end_ms=2500,
    )

    result = CandidateScorer().score(
        _beat(),
        candidate,
        needed_duration_ms=1000,
        previous_clip=previous,
    )

    assert 0.0 < result.continuity_bonus <= 0.03


def test_overlapping_same_video_range_gets_no_continuity_bonus() -> None:
    video_id = uuid4()
    previous = _previous_clip(video_id=video_id, source_in_ms=0, source_out_ms=1000)
    candidate = _hit(
        video_id=video_id,
        source_start_ms=500,
        source_end_ms=1500,
    )

    result = CandidateScorer().score(
        _beat(),
        candidate,
        needed_duration_ms=1000,
        previous_clip=previous,
    )

    assert result.continuity_bonus == 0.0


def test_reuse_penalty_is_progressive_and_capped() -> None:
    scorer = CandidateScorer()
    one_use = scorer.score(
        _beat(),
        _hit(),
        needed_duration_ms=1000,
        prior_use_count=1,
    )
    many_uses = scorer.score(
        _beat(),
        _hit(),
        needed_duration_ms=1000,
        prior_use_count=10,
    )

    assert one_use.reuse_penalty == pytest.approx(0.08)
    assert many_uses.reuse_penalty == pytest.approx(0.20)


def test_equal_candidate_inputs_keep_equal_scores_for_planner_tie_breaking() -> None:
    scorer = CandidateScorer()
    first = scorer.score(_beat(), _hit(score=0.8), needed_duration_ms=1000)
    second = scorer.score(_beat(), _hit(score=0.8), needed_duration_ms=1000)

    assert first.total_score == second.total_score
    assert first.semantic_score == second.semantic_score

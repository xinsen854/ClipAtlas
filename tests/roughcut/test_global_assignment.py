from uuid import uuid4

from clipatlas.roughcut.global_assignment import (
    AssignmentCandidate,
    assign_requirements,
)


def _candidate(
    requirement_id: str,
    *,
    video_id=None,
    start_ms: int,
    end_ms: int,
    score: float,
    level: str = "DIRECT",
    importance: str = "S",
    sentence_id: str = "sentence-0",
    anchor_start_ms: int | None = None,
    anchor_end_ms: int | None = None,
    pollution_level: str = "clean",
):
    return AssignmentCandidate(
        requirement_id=requirement_id,
        sentence_id=sentence_id,
        importance=importance,
        video_id=video_id or uuid4(),
        start_ms=start_ms,
        end_ms=end_ms,
        score=score,
        match_level=level,
        anchor_start_ms=anchor_start_ms,
        anchor_end_ms=anchor_end_ms,
        pollution_level=pollution_level,
    )


def test_global_assignment_reserves_unique_s_direct_candidate():
    shared_video = uuid4()
    shared = _candidate(
        "general", video_id=shared_video, start_ms=0, end_ms=8000, score=0.95,
    )
    general_alt = _candidate(
        "general", start_ms=0, end_ms=8000, score=0.90,
    )
    unique = _candidate(
        "specific", video_id=shared_video, start_ms=0, end_ms=8000, score=0.98,
    )

    selected = assign_requirements({
        "general": [shared, general_alt],
        "specific": [unique],
    })

    assert selected["specific"].video_id == shared_video
    assert selected["general"].video_id != shared_video


def test_global_assignment_prefers_unused_75_over_recently_used_80():
    used_video = uuid4()
    used = _candidate(
        "s1", video_id=used_video, start_ms=1000, end_ms=9000, score=0.80,
    )
    fresh = _candidate("s1", start_ms=1000, end_ms=9000, score=0.75)

    selected = assign_requirements(
        {"s1": [used, fresh]},
        batch_usage={str(used_video): [(1000, 9000, 0)]},
        current_batch_index=1,
        reuse_gap=5,
    )

    assert selected["s1"].video_id == fresh.video_id


def test_global_assignment_allows_controlled_reuse_when_no_legal_alternative():
    used_video = uuid4()
    used = _candidate(
        "s1", video_id=used_video, start_ms=1000, end_ms=9000, score=0.80,
    )

    selected = assign_requirements(
        {"s1": [used]},
        batch_usage={str(used_video): [(1000, 9000, 0)]},
        current_batch_index=1,
        reuse_gap=5,
    )

    assert selected["s1"].video_id == used_video
    assert selected["s1"].controlled_reuse is True


def test_global_assignment_never_selects_blocked_pollution():
    blocked = _candidate(
        "s1", start_ms=0, end_ms=8000, score=0.99, pollution_level="blocked",
    )
    clean = _candidate("s1", start_ms=0, end_ms=8000, score=0.60)

    selected = assign_requirements({"s1": [blocked, clean]})

    assert selected["s1"].video_id == clean.video_id


def test_global_assignment_prefers_full_sentence_capacity_before_score():
    full = _candidate("s1", start_ms=0, end_ms=10_000, score=0.82)
    short = _candidate("s1", start_ms=0, end_ms=3500, score=0.95)

    selected = assign_requirements(
        {"s1": [short, full]},
        required_duration_ms={"s1": 9000},
    )

    assert selected["s1"].video_id == full.video_id


def test_global_assignment_prefers_anchor_that_can_cover_s_focus():
    plain = _candidate("s1", start_ms=0, end_ms=9000, score=0.90)
    anchored = _candidate(
        "s1", start_ms=0, end_ms=9000, score=0.86,
        anchor_start_ms=4000, anchor_end_ms=7000,
    )

    selected = assign_requirements({"s1": [plain, anchored]})

    assert selected["s1"].video_id == anchored.video_id

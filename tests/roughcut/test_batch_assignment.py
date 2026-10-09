from types import SimpleNamespace
from uuid import uuid4

from clipatlas.roughcut.batch_assignment import batch_assignment_order, batch_usage_from_plans


def _plan(*, candidates: int, direct: int, s_beats: int):
    beats = [SimpleNamespace(retrieval_intent={"director_importance": "S"}) for _ in range(s_beats)]
    matrix = [
        {"candidate_id": str(uuid4())}
        for _ in range(candidates)
    ]
    if beats:
        beats[0].retrieval_intent["candidate_matrix"] = matrix
    clips = [
        SimpleNamespace(
            director_fit="DIRECT",
            video_id=uuid4(),
            source_in_ms=index * 1000,
            source_out_ms=(index + 1) * 1000,
        )
        for index in range(direct)
    ]
    return SimpleNamespace(beats=beats, clips=clips)


def test_batch_assignment_protects_scarce_candidates_first():
    common = _plan(candidates=5, direct=1, s_beats=1)
    scarce = _plan(candidates=1, direct=1, s_beats=1)
    assert batch_assignment_order([common, scarce]) == [1, 0]


def test_batch_usage_preserves_source_ranges_and_batch_index():
    video_id = uuid4()
    plan = SimpleNamespace(clips=[SimpleNamespace(
        video_id=video_id, source_in_ms=100, source_out_ms=500,
    )])
    usage = batch_usage_from_plans([plan])
    assert usage[str(video_id)] == [(100, 500, 0)]


def test_batch_usage_does_not_double_charge_overlapping_ranges_in_one_output():
    video_id = uuid4()
    plan = SimpleNamespace(clips=[
        SimpleNamespace(video_id=video_id, source_in_ms=100, source_out_ms=900),
        SimpleNamespace(video_id=video_id, source_in_ms=500, source_out_ms=1200),
        SimpleNamespace(video_id=video_id, source_in_ms=1500, source_out_ms=2000),
    ])

    usage = batch_usage_from_plans([plan])

    assert usage[str(video_id)] == [
        (100, 900, 0),
        (1500, 2000, 0),
    ]

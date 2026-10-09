from uuid import uuid4

from clipatlas.retrieval.evaluation import RecallWindow, recall_at_k


def test_recall_at_20_is_candidate_coverage_not_exact_accuracy():
    video_id = uuid4()
    expected = [RecallWindow(video_id, 10_000, 14_000)]
    candidates = [RecallWindow(video_id, 9_500, 14_500)]
    assert recall_at_k(expected, candidates, k=20) == 1.0

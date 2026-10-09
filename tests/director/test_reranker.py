import json

import httpx

from clipatlas.director.reranker import CandidateReranker, RerankCandidate


class _FakeClient(httpx.AsyncClient):
    def __init__(self, response_payload: dict) -> None:
        super().__init__()
        self.response_payload = response_payload
        self.sent: dict | None = None
        self.calls = 0

    async def post(self, url: str, **kwargs) -> httpx.Response:
        self.calls += 1
        self.sent = kwargs.get("json")
        return httpx.Response(
            200,
            json=self.response_payload,
            request=httpx.Request("POST", url),
        )


def _candidate(candidate_id: str, score: float, *, level: str = "DIRECT") -> RerankCandidate:
    return RerankCandidate(
        candidate_id=candidate_id,
        requirement_id="req-1",
        source_quote="泰钽700在贵州盘山路向上爬坡",
        match_level=level,
        local_score=score,
        subject="泰钽700",
        action="爬坡",
        scene="贵州盘山路",
        evidence_summary="泰钽700在贵州盘山碎石路持续向上爬坡",
        source_start_ms=10_000,
        source_end_ms=20_000,
        pollution_level="clean",
    )


async def test_reranker_uses_one_api_call_for_candidate_snapshot():
    fake = _FakeClient({
        "choices": [{"message": {"content": json.dumps({
            "rankings": [{"requirement_id": "req-1", "candidate_ids": ["c2", "c1"]}]
        }, ensure_ascii=False)}}]
    })
    reranker = CandidateReranker(
        api_key="key", base_url="https://example.com/v1", client=fake,
    )

    ranked = await reranker.rank([_candidate("c1", 0.9), _candidate("c2", 0.8)])

    assert fake.calls == 1
    assert ranked["req-1"] == ["c2", "c1"]
    assert fake.sent is not None
    prompt = fake.sent["messages"][0]["content"]
    assert "不能创造新的 candidate_id" in prompt
    assert "不能改变 DIRECT/SUPPORT" in prompt


async def test_reranker_drops_unknown_ids_and_keeps_all_legal_candidates():
    fake = _FakeClient({
        "choices": [{"message": {"content": json.dumps({
            "rankings": [{
                "requirement_id": "req-1",
                "candidate_ids": ["made-up", "c2"],
            }]
        })}}]
    })
    reranker = CandidateReranker(
        api_key="key", base_url="https://example.com/v1", client=fake,
    )

    ranked = await reranker.rank([_candidate("c1", 0.9), _candidate("c2", 0.8)])

    assert ranked["req-1"] == ["c2", "c1"]


async def test_reranker_never_submits_reject_or_blocked_candidates():
    fake = _FakeClient({
        "choices": [{"message": {"content": json.dumps({
            "rankings": [{"requirement_id": "req-1", "candidate_ids": ["clean"]}]
        })}}]
    })
    reranker = CandidateReranker(
        api_key="key", base_url="https://example.com/v1", client=fake,
    )
    candidates = [
        _candidate("clean", 0.7),
        _candidate("reject", 0.99, level="REJECT"),
        _candidate("blocked", 0.98).model_copy(update={"pollution_level": "blocked"}),
    ]

    ranked = await reranker.rank(candidates)

    assert ranked["req-1"] == ["clean"]
    body = fake.sent["messages"][1]["content"]
    assert "reject" not in body
    assert "blocked" not in body


async def test_reranker_failure_falls_back_to_local_order():
    class _FailingClient(httpx.AsyncClient):
        async def post(self, url: str, **kwargs) -> httpx.Response:
            raise httpx.ConnectError("offline", request=httpx.Request("POST", url))

    reranker = CandidateReranker(
        api_key="key", base_url="https://example.com/v1", client=_FailingClient(),
    )

    ranked = await reranker.rank([_candidate("c1", 0.9), _candidate("c2", 0.8)])

    assert ranked["req-1"] == ["c1", "c2"]

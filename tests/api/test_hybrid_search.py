from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from clipatlas.api.routes.search import router
from clipatlas.retrieval.hybrid import HybridSearchHit


class FakeHybridSearch:
    async def search(self, query: str, limit: int = 10, video_ids=None):
        video_id = uuid4()
        return [
            HybridSearchHit(
                video_id=video_id,
                filename="movie.mp4",
                source_uri="file:///tmp/movie.mp4",
                source_start_ms=1_000,
                source_end_ms=6_000,
                score=1.8,
                visual_score=0.8,
                asr_score=1.0,
                ocr_score=None,
                sources=["visual", "asr"],
                asr_texts=["越野测试"],
                ocr_texts=[],
            )
        ]


def _client() -> TestClient:
    app = FastAPI()
    app.state.hybrid_search_service = FakeHybridSearch()
    app.include_router(router)
    return TestClient(app)


def test_hybrid_search_endpoint_returns_source_scores_and_provenance() -> None:
    response = _client().get(
        "/api/v1/search/hybrid",
        params={"q": "越野测试", "limit": 5},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["score"] == 1.8
    assert body[0]["visual_score"] == 0.8
    assert body[0]["asr_score"] == 1.0
    assert body[0]["ocr_score"] is None
    assert body[0]["sources"] == ["visual", "asr"]
    assert body[0]["asr_texts"] == ["越野测试"]


def test_hybrid_search_endpoint_rejects_blank_query() -> None:
    response = _client().get(
        "/api/v1/search/hybrid",
        params={"q": "   "},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "query must not be blank"

from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from clipatlas.domain.models import AnnotationOrigin, SemanticAnnotation
from clipatlas.main import create_app
from clipatlas.retrieval.search import SemanticSearchHit


class FakeSearchService:
    def __init__(self, hit: SemanticSearchHit) -> None:
        self._hit = hit
        self.calls: list[tuple[str, int, list[UUID] | None]] = []

    async def search(
        self,
        query: str,
        limit: int = 10,
        video_ids: list[UUID] | None = None,
    ) -> list[SemanticSearchHit]:
        self.calls.append((query, limit, video_ids))
        return [self._hit]


def _configured_app(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CLIPATLAS_LIBRARY_DB", str(tmp_path / "library.sqlite3"))
    monkeypatch.setenv("CLIPATLAS_LIBRARY_CACHE_ROOT", str(tmp_path / "cache"))
    monkeypatch.delenv("CLIPATLAS_EMBEDDING_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    return create_app()


def _hit() -> SemanticSearchHit:
    segment_id = uuid4()
    video_id = uuid4()
    annotation = SemanticAnnotation(
        segment_id=segment_id,
        origin=AnnotationOrigin.HUMAN,
        description="一个男人独自在雨夜街头行走",
        revision=2,
    )
    return SemanticSearchHit(
        segment_id=segment_id,
        video_id=video_id,
        source_uri="file:///media/rain.mp4",
        source_start_ms=12_345,
        source_end_ms=18_765,
        score=0.987,
        effective_description=annotation.description,
        annotation=annotation,
        embedding_provider="fake-embedding",
        embedding_model="embed-v1",
        embedding_dimensions=3,
    )


def test_search_segments_returns_exact_source_fields(tmp_path: Path, monkeypatch) -> None:
    hit = _hit()
    service = FakeSearchService(hit)
    app = _configured_app(tmp_path, monkeypatch)
    app.state.semantic_search_service = service

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/search/segments",
            params={"q": "孤独男人在雨里走路", "limit": 7},
        )

    assert response.status_code == 200
    assert service.calls == [("孤独男人在雨里走路", 7, None)]
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["segment_id"] == str(hit.segment_id)
    assert payload[0]["video_id"] == str(hit.video_id)
    assert payload[0]["source_uri"] == "file:///media/rain.mp4"
    assert payload[0]["source_start_ms"] == 12_345
    assert payload[0]["source_end_ms"] == 18_765
    assert payload[0]["effective_description"] == hit.annotation.description
    assert payload[0]["embedding_provider"] == "fake-embedding"
    assert payload[0]["embedding_model"] == "embed-v1"
    assert payload[0]["embedding_dimensions"] == 3


def test_search_segments_forwards_video_scope_filter(tmp_path: Path, monkeypatch) -> None:
    hit = _hit()
    service = FakeSearchService(hit)
    app = _configured_app(tmp_path, monkeypatch)
    app.state.semantic_search_service = service
    video_ids = [uuid4(), uuid4()]

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/search/segments",
            params=[
                ("q", "雨夜街头"),
                ("limit", "5"),
                ("video_ids", str(video_ids[0])),
                ("video_ids", str(video_ids[1])),
            ],
        )

    assert response.status_code == 200
    assert service.calls == [("雨夜街头", 5, video_ids)]


def test_search_segments_resolves_empty_project_scope_without_using_all_videos(
    tmp_path: Path, monkeypatch,
) -> None:
    hit = _hit()
    service = FakeSearchService(hit)
    app = _configured_app(tmp_path, monkeypatch)
    app.state.semantic_search_service = service
    project_id = uuid4()

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/search/segments",
            params={"q": "雨夜街头", "project_id": str(project_id)},
        )

    assert response.status_code == 200
    assert service.calls == [("雨夜街头", 10, [])]


def test_search_segments_validates_query_and_limit(tmp_path: Path, monkeypatch) -> None:
    app = _configured_app(tmp_path, monkeypatch)

    with TestClient(app) as client:
        assert client.get("/api/v1/search/segments").status_code == 422
        assert client.get("/api/v1/search/segments", params={"q": "x", "limit": 0}).status_code == 422
        assert client.get("/api/v1/search/segments", params={"q": "x", "limit": 101}).status_code == 422


def test_search_segments_returns_503_when_embedding_runtime_is_disabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = _configured_app(tmp_path, monkeypatch)

    with TestClient(app) as client:
        response = client.get("/api/v1/search/segments", params={"q": "rain"})

    assert response.status_code == 503
    assert response.json()["detail"] == "semantic search is not configured"

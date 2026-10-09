from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from clipatlas.main import create_app
from clipatlas.retrieval.search import CoarseVideoSearchHit
from clipatlas.retrieval.video_profiles import VideoIndexProfile


class FakeVideoChunkSearchService:
    def __init__(self, hit: CoarseVideoSearchHit) -> None:
        self._hit = hit
        self.calls: list[tuple[str, int, list[UUID] | None, VideoIndexProfile]] = []

    async def search(
        self,
        query: str,
        limit: int = 10,
        video_ids: list[UUID] | None = None,
        profile: VideoIndexProfile | None = None,
    ) -> list[CoarseVideoSearchHit]:
        assert profile is not None
        self.calls.append((query, limit, video_ids, profile))
        return [self._hit]


def _configured_app(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CLIPATLAS_LIBRARY_DB", str(tmp_path / "library.sqlite3"))
    monkeypatch.setenv("CLIPATLAS_LIBRARY_CACHE_ROOT", str(tmp_path / "cache"))
    monkeypatch.delenv("CLIPATLAS_EMBEDDING_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    return create_app()


def _hit() -> CoarseVideoSearchHit:
    return CoarseVideoSearchHit(
        video_id=uuid4(),
        filename="road.mp4",
        source_uri="file:///media/road.mp4",
        source_start_ms=12_000,
        source_end_ms=17_000,
        score=0.91,
        embedding_provider="qwen-vl-video",
        embedding_model="qwen3-vl-embedding",
        embedding_dimensions=2560,
        chunk_duration_ms=5_000,
        overlap_ms=1_000,
    )


def test_video_chunk_search_defaults_to_5s_profile(tmp_path: Path, monkeypatch) -> None:
    hit = _hit()
    service = FakeVideoChunkSearchService(hit)
    app = _configured_app(tmp_path, monkeypatch)
    app.state.video_chunk_search_service = service

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/search/video-chunks",
            params={"q": "夜间山路上的汽车", "limit": 8},
        )

    assert response.status_code == 200
    assert len(service.calls) == 1
    query, limit, video_ids, profile = service.calls[0]
    assert (query, limit, video_ids) == ("夜间山路上的汽车", 8, None)
    assert profile.key == "5s"
    payload = response.json()[0]
    assert payload["video_id"] == str(hit.video_id)
    assert payload["source_start_ms"] == 12_000
    assert payload["source_end_ms"] == 17_000
    assert payload["chunk_duration_ms"] == 5_000
    assert payload["overlap_ms"] == 1_000
    assert payload["embedding_model"] == "qwen3-vl-embedding"
    assert payload["embedding_dimensions"] == 2560


def test_video_chunk_search_can_explicitly_select_30s_profile(tmp_path: Path, monkeypatch) -> None:
    service = FakeVideoChunkSearchService(_hit())
    app = _configured_app(tmp_path, monkeypatch)
    app.state.video_chunk_search_service = service
    video_ids = [uuid4(), uuid4()]

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/search/video-chunks",
            params=[
                ("q", "发布会大屏"),
                ("granularity", "30s"),
                ("video_ids", str(video_ids[0])),
                ("video_ids", str(video_ids[1])),
            ],
        )

    assert response.status_code == 200
    assert service.calls[0][2] == video_ids
    assert service.calls[0][3].key == "30s"


def test_video_chunk_search_rejects_abandoned_1s_profile(tmp_path: Path, monkeypatch) -> None:
    app = _configured_app(tmp_path, monkeypatch)
    app.state.video_chunk_search_service = FakeVideoChunkSearchService(_hit())

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/search/video-chunks",
            params={"q": "汽车", "granularity": "1s"},
        )

    assert response.status_code == 422


def test_video_chunk_search_returns_503_when_runtime_is_disabled(tmp_path: Path, monkeypatch) -> None:
    app = _configured_app(tmp_path, monkeypatch)

    with TestClient(app) as client:
        response = client.get("/api/v1/search/video-chunks", params={"q": "汽车"})

    assert response.status_code == 503
    assert response.json()["detail"] == "video chunk search is not configured"

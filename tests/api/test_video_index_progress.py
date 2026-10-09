import sqlite3
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from clipatlas.api.routes.videos import router
from clipatlas.catalog.store import CatalogStore
from clipatlas.library.index_progress import IndexSourceProgress, VideoIndexProgress


class FakeProgressReader:
    def __init__(self, result: VideoIndexProgress) -> None:
        self.result = result
        self.calls = []

    def get(self, video_id):
        self.calls.append(video_id)
        return self.result


def _video(catalog: CatalogStore, db_path: Path):
    video_id = uuid4()
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO catalog_videos (
                id, filename, source_uri, duration_ms, width, height, fps,
                video_codec, has_audio, created_at
            ) VALUES (?, 'movie.mp4', 'file:///movie.mp4', 10000, 1920, 1080,
                      25.0, 'h264', 1, '2026-09-05T00:00:00+00:00')
            """,
            (str(video_id),),
        )
    return video_id


def _client(tmp_path: Path):
    db_path = tmp_path / "library.sqlite3"
    catalog = CatalogStore(db_path)
    progress = VideoIndexProgress(
        visual=IndexSourceProgress(enabled=True, completed=2, processing=1, failed=0, total=3),
        asr=IndexSourceProgress(enabled=True, completed=1, processing=0, failed=0, total=1),
        ocr=IndexSourceProgress(enabled=False, completed=0, processing=0, failed=0, total=0),
    )
    reader = FakeProgressReader(progress)
    app = FastAPI()
    app.state.library_catalog = catalog
    app.state.library_index_progress = reader
    app.include_router(router)
    return TestClient(app), catalog, reader, db_path


def test_video_index_progress_returns_reader_projection(tmp_path: Path) -> None:
    client, catalog, reader, db_path = _client(tmp_path)
    video_id = _video(catalog, db_path)

    response = client.get(f"/api/v1/videos/{video_id}/index-progress")

    assert response.status_code == 200
    assert response.json()["visual"] == {
        "enabled": True, "applicable": True,
        "completed": 2, "processing": 1, "failed": 0, "total": 3,
    }
    assert reader.calls == [video_id]


def test_video_index_progress_preserves_video_404(tmp_path: Path) -> None:
    client, _, _, _ = _client(tmp_path)

    response = client.get(f"/api/v1/videos/{uuid4()}/index-progress")

    assert response.status_code == 404
    assert response.json()["detail"] == "video not found"

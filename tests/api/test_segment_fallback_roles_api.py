from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from clipatlas.api.routes.segment_roles import router as segment_roles_router
from clipatlas.catalog.store import CatalogStore
from clipatlas.domain.models import SegmentSource


def _app_with_segment(tmp_path: Path):
    catalog = CatalogStore(tmp_path / "library.sqlite3")
    video_id = uuid4()
    segment_id = uuid4()
    with catalog._connect() as connection:
        connection.execute(
            "INSERT INTO catalog_videos (id,filename,source_uri,duration_ms,width,height,fps,video_codec,has_audio,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (str(video_id), "a.mp4", "file:///a.mp4", 10_000, 1920, 1080, 25.0, "h264", 0,
             "2026-01-01T00:00:00+00:00"),
        )
        connection.execute(
            "INSERT INTO catalog_segments (id,video_id,start_ms,end_ms,source,created_at) VALUES (?,?,?,?,?,?)",
            (str(segment_id), str(video_id), 1000, 9000, SegmentSource.AI.value,
             "2026-01-01T00:00:00+00:00"),
        )
    app = FastAPI()
    app.include_router(segment_roles_router)
    app.state.library_catalog = catalog
    return app, segment_id


def test_segment_fallback_role_can_be_marked_generic_over_api(tmp_path: Path):
    app, segment_id = _app_with_segment(tmp_path)
    client = TestClient(app)

    response = client.patch(
        f"/api/v1/library/segments/{segment_id}/fallback-role",
        json={"role": "generic"},
    )

    assert response.status_code == 200
    assert response.json() == {"segment_id": str(segment_id), "role": "generic"}
    readback = client.get(f"/api/v1/library/segments/{segment_id}/fallback-role")
    assert readback.status_code == 200
    assert readback.json()["role"] == "generic"


def test_segment_can_be_reserved_as_review_placeholder_over_api(tmp_path: Path):
    app, segment_id = _app_with_segment(tmp_path)
    client = TestClient(app)

    response = client.patch(
        f"/api/v1/library/segments/{segment_id}/fallback-role",
        json={"role": "review_placeholder"},
    )

    assert response.status_code == 200
    assert response.json()["role"] == "review_placeholder"


def test_unknown_segment_fallback_role_returns_404(tmp_path: Path):
    catalog = CatalogStore(tmp_path / "library.sqlite3")
    app = FastAPI()
    app.include_router(segment_roles_router)
    app.state.library_catalog = catalog
    client = TestClient(app)

    response = client.patch(
        f"/api/v1/library/segments/{uuid4()}/fallback-role",
        json={"role": "generic"},
    )

    assert response.status_code == 404

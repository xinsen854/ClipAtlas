from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from clipatlas.api.routes.finecut import router as finecut_router
from finecut.models import Clip, TimelineDocument, Track


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(finecut_router)
    return TestClient(app)


def _payload() -> tuple[dict[str, object], Clip]:
    clip = Clip(
        source_id="source-a",
        source_path="D:/media/source-a.mp4",
        timeline_start_ms=0,
        duration_ms=5000,
        source_in_ms=1000,
        source_out_ms=6000,
    )
    document = TimelineDocument(
        project_id=uuid4(),
        source_plan_id=uuid4(),
        width=1920,
        height=1080,
        fps=30,
        duration_ms=5000,
        tracks=[Track(kind="video", clips=[clip])],
    )
    return {
        "document": document.model_dump(mode="json"),
        "target_clip_id": str(clip.id),
        "opacity": 0.6,
        "volume": 0.4,
        "transform": {
            "position_x": 20.0,
            "position_y": -10.0,
            "scale": 1.2,
            "rotation": 12.0,
        },
    }, clip


def test_properties_api_updates_existing_clip_fields_only() -> None:
    client = _client()
    payload, original = _payload()
    response = client.post("/api/v1/finecut/edit/properties", json=payload)
    assert response.status_code == 200
    result = response.json()["tracks"][0]["clips"][0]
    assert result["id"] == str(original.id)
    assert result["source_id"] == original.source_id
    assert result["timeline_start_ms"] == original.timeline_start_ms
    assert result["opacity"] == 0.6
    assert result["volume"] == 0.4
    assert result["transform"] == {
        "position_x": 20.0,
        "position_y": -10.0,
        "scale": 1.2,
        "rotation": 12.0,
    }
    assert result["effects"] == []


def test_properties_api_rejects_unsupported_transform_key() -> None:
    client = _client()
    payload, _ = _payload()
    payload["transform"] = {"anchor_x": 1.0}
    response = client.post("/api/v1/finecut/edit/properties", json=payload)
    assert response.status_code == 400
    assert "unsupported transform key" in response.json()["detail"]

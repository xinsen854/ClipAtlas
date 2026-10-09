from uuid import uuid4

from fastapi.testclient import TestClient

from clipatlas.main import create_app
from clipatlas.providers.fake import FakeVideoUnderstandingProvider
from clipatlas.providers.registry import ProviderRegistry


def make_client() -> TestClient:
    registry = ProviderRegistry()
    registry.register(FakeVideoUnderstandingProvider())
    return TestClient(create_app(registry))


def test_list_providers_returns_capabilities():
    client = make_client()

    response = client.get("/api/v1/providers")

    assert response.status_code == 200
    payload = response.json()
    assert payload["providers"][0]["name"] == "fake"
    assert payload["providers"][0]["capabilities"]["image_input"] is True
    assert payload["providers"][0]["capabilities"]["structured_output"] is True


def test_analyze_segment_uses_selected_provider():
    client = make_client()
    segment_id = uuid4()
    body = {
        "video_id": str(uuid4()),
        "segment_id": str(segment_id),
        "start_ms": 1200,
        "end_ms": 3200,
        "source_uri": "file:///video.mp4",
        "frame_uris": [],
        "context": {"language": "zh-CN"},
    }

    response = client.post("/api/v1/providers/fake/analyze-segment", json=body)

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "fake"
    assert payload["annotation"]["segment_id"] == str(segment_id)
    assert payload["annotation"]["raw_payload"]["start_ms"] == 1200


def test_missing_provider_returns_stable_404_error():
    client = make_client()
    body = {
        "video_id": str(uuid4()),
        "segment_id": str(uuid4()),
        "start_ms": 0,
        "end_ms": 1000,
        "source_uri": "file:///video.mp4",
    }

    response = client.post("/api/v1/providers/missing/analyze-segment", json=body)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "provider_not_found"

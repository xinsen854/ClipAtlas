from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from clipatlas.api.routes.finecut import router as finecut_router
from finecut.models import CandidateItem, Clip, MediaReference, TimelineDocument, Track


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(finecut_router)
    return TestClient(app)


def _document_payload(*, duration_ms: int = 5000) -> tuple[TimelineDocument, Clip]:
    clip = Clip(
        source_id="original",
        source_path="D:/media/original.mp4",
        timeline_start_ms=2000,
        duration_ms=duration_ms,
        source_in_ms=1000,
        source_out_ms=1000 + duration_ms,
    )
    document = TimelineDocument(
        project_id=uuid4(),
        source_plan_id=uuid4(),
        width=1920,
        height=1080,
        fps=30,
        duration_ms=10_000,
        tracks=[Track(kind="video", clips=[clip])],
    )
    return document, clip


def _payload(*, candidate_duration_ms: int = 7000) -> tuple[dict[str, object], Clip]:
    document, clip = _document_payload()
    candidate = CandidateItem(
        requirement_id="req-1",
        candidate_type="window",
        media_id=uuid4(),
        source_in_ms=3000,
        source_out_ms=3000 + candidate_duration_ms,
        display_level="S",
    )
    media = MediaReference(
        media_id=candidate.media_id,
        source_uri="D:/media/replacement.mp4",
    )
    return {
        "document": document.model_dump(mode="json"),
        "target_clip_id": str(clip.id),
        "candidate": candidate.model_dump(mode="json"),
        "media": media.model_dump(mode="json"),
    }, clip


def test_replace_api_uses_one_finecut_edit_rule() -> None:
    client = _client()
    payload, original = _payload()
    response = client.post("/api/v1/finecut/edit/replace", json=payload)
    assert response.status_code == 200
    clip = response.json()["tracks"][0]["clips"][0]
    assert clip["id"] == str(original.id)
    assert clip["timeline_start_ms"] == original.timeline_start_ms
    assert clip["duration_ms"] == original.duration_ms
    assert clip["source_path"] == "D:/media/replacement.mp4"
    assert clip["source_in_ms"] == 3000
    assert clip["source_out_ms"] == 8000


def test_replace_api_rejects_short_candidate_without_extending_it() -> None:
    client = _client()
    payload, _ = _payload(candidate_duration_ms=4999)
    response = client.post("/api/v1/finecut/edit/replace", json=payload)
    assert response.status_code == 400
    assert response.json()["detail"] == "candidate duration is shorter than timeline slot"


def test_trim_api_applies_left_edge_rule() -> None:
    client = _client()
    document, clip = _document_payload()
    response = client.post(
        "/api/v1/finecut/edit/trim",
        json={
            "document": document.model_dump(mode="json"),
            "target_clip_id": str(clip.id),
            "edge": "left",
            "delta_ms": 750,
        },
    )
    assert response.status_code == 200
    result = response.json()["tracks"][0]["clips"][0]
    assert result["timeline_start_ms"] == 2750
    assert result["duration_ms"] == 4250
    assert result["source_in_ms"] == 1750
    assert result["source_out_ms"] == 6000


def test_split_api_returns_two_continuous_clips() -> None:
    client = _client()
    document, clip = _document_payload(duration_ms=6000)
    response = client.post(
        "/api/v1/finecut/edit/split",
        json={
            "document": document.model_dump(mode="json"),
            "target_clip_id": str(clip.id),
            "split_timeline_ms": 5000,
        },
    )
    assert response.status_code == 200
    left, right = response.json()["tracks"][0]["clips"]
    assert left["timeline_start_ms"] + left["duration_ms"] == right["timeline_start_ms"]
    assert left["source_out_ms"] == right["source_in_ms"]
    assert left["duration_ms"] + right["duration_ms"] == 6000


def test_delete_api_removes_only_target_clip() -> None:
    client = _client()
    document, clip = _document_payload(duration_ms=2000)
    second = Clip(
        source_id="second",
        source_path="D:/media/second.mp4",
        timeline_start_ms=6000,
        duration_ms=2000,
        source_in_ms=500,
        source_out_ms=2500,
    )
    document.tracks[0].clips.append(second)
    response = client.post(
        "/api/v1/finecut/edit/delete",
        json={
            "document": document.model_dump(mode="json"),
            "target_clip_id": str(clip.id),
        },
    )
    assert response.status_code == 200
    clips = response.json()["tracks"][0]["clips"]
    assert [item["id"] for item in clips] == [str(second.id)]
    assert clips[0]["timeline_start_ms"] == second.timeline_start_ms

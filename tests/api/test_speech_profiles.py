from pathlib import Path
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from clipatlas.api.routes.speech import router as speech_router
from clipatlas.speech.fake import FakeSpeechProvider
from clipatlas.speech.registry import SpeechProviderRegistry
from clipatlas.speech.store import NarrationStore


def build_test_app(tmp_path: Path) -> FastAPI:
    app = FastAPI()
    app.include_router(speech_router)
    registry = SpeechProviderRegistry()
    registry.register(FakeSpeechProvider())
    app.state.speech_registry = registry
    app.state.narration_store = NarrationStore(tmp_path / "speech.sqlite3")
    return app


def test_manual_profile_accepts_custom_voice_id_and_controls(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    client = TestClient(app)
    project_id = uuid4()

    response = client.post(
        "/api/v1/speech/profiles",
        json={
            "project_id": str(project_id),
            "provider": "fake",
            "voice_id": "custom-clone-001",
            "gender_constraint": "female",
            "age_style_constraint": "mature",
            "language": "zh-CN",
            "accent": "mandarin",
            "speed": 0.93,
            "pitch": 1.05,
            "volume": 0.88,
            "emotion": "calm",
            "style": "documentary",
            "instruction": "自然、克制",
            "locked": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["project_id"] == str(project_id)
    assert body["provider"] == "fake"
    assert body["model"] == "fake-tts-v0.1"
    assert body["voice_id"] == "custom-clone-001"
    assert body["gender_constraint"] == "female"
    assert body["age_style_constraint"] == "mature"
    assert body["speed"] == 0.93
    assert body["pitch"] == 1.05
    assert body["volume"] == 0.88
    assert body["emotion"] == "calm"
    assert body["style"] == "documentary"
    assert body["instruction"] == "自然、克制"
    assert body["random_mode"] == "none"
    assert body["locked"] is True
    assert body["revision"] == 1

    stored = app.state.narration_store.get_profile(UUID(body["id"]))
    assert stored is not None
    assert stored.voice_id == "custom-clone-001"


def test_patch_profile_creates_new_revision_without_overwriting_history(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    client = TestClient(app)
    project_id = uuid4()

    created = client.post(
        "/api/v1/speech/profiles",
        json={
            "project_id": str(project_id),
            "provider": "fake",
            "voice_id": "custom-clone-001",
            "speed": 1.0,
            "locked": True,
        },
    )
    assert created.status_code == 200
    original = created.json()

    updated = client.patch(
        f"/api/v1/speech/profiles/{original['id']}",
        json={
            "voice_id": "custom-clone-002",
            "speed": 0.9,
            "pitch": 1.08,
            "style": "warm",
            "locked": False,
        },
    )

    assert updated.status_code == 200
    revised = updated.json()
    assert revised["id"] != original["id"]
    assert revised["revision"] == original["revision"] + 1
    assert revised["voice_id"] == "custom-clone-002"
    assert revised["speed"] == 0.9
    assert revised["pitch"] == 1.08
    assert revised["style"] == "warm"
    assert revised["locked"] is False

    original_stored = app.state.narration_store.get_profile(UUID(original["id"]))
    revised_stored = app.state.narration_store.get_profile(UUID(revised["id"]))
    assert original_stored is not None
    assert revised_stored is not None
    assert original_stored.voice_id == "custom-clone-001"
    assert original_stored.speed == 1.0
    assert original_stored.locked is True
    assert revised_stored.voice_id == "custom-clone-002"


def test_list_project_speech_profiles_returns_revision_history(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    client = TestClient(app)
    project_id = uuid4()

    first = client.post(
        "/api/v1/speech/profiles",
        json={
            "project_id": str(project_id),
            "provider": "fake",
            "voice_id": "voice-1",
            "locked": True,
        },
    )
    assert first.status_code == 200
    second = client.patch(
        f"/api/v1/speech/profiles/{first.json()['id']}",
        json={"voice_id": "voice-2", "locked": False},
    )
    assert second.status_code == 200

    response = client.get(f"/api/v1/projects/{project_id}/speech-profiles")

    assert response.status_code == 200
    assert [profile["id"] for profile in response.json()] == [
        second.json()["id"],
        first.json()["id"],
    ]
    assert client.get(f"/api/v1/projects/{uuid4()}/speech-profiles").json() == []

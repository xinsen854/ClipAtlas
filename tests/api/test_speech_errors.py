from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from clipatlas.api.errors import register_error_handlers
from clipatlas.api.routes.speech import router as speech_router
from clipatlas.speech.errors import (
    SpeechAudioValidationError,
    SpeechAuthenticationError,
    SpeechConfigurationError,
    SpeechRateLimitError,
    SpeechRequestError,
)
from clipatlas.speech.models import NarrationTrack, SpeechProfile
from clipatlas.speech.store import NarrationStore


class FailingNarrationService:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def create_tts_track(
        self,
        project_id: UUID,
        script: str,
        profile: SpeechProfile,
    ) -> NarrationTrack:
        del project_id, script, profile
        raise self.error


def _app(tmp_path: Path, service: object | None) -> tuple[FastAPI, NarrationStore]:
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(speech_router)
    store = NarrationStore(tmp_path / "speech.sqlite3")
    app.state.narration_store = store
    if service is not None:
        app.state.narration_service = service
    return app, store


def _saved_profile(store: NarrationStore, project_id: UUID) -> SpeechProfile:
    profile = SpeechProfile(
        project_id=project_id,
        provider="dashscope",
        model="cosyvoice-v3.5-flash",
        voice_id="custom-voice-001",
        locked=True,
    )
    store.save_profile(profile)
    return profile


@pytest.mark.parametrize(
    ("error", "status_code", "error_code"),
    [
        (SpeechAuthenticationError("invalid api key"), 502, "speech_auth_failed"),
        (SpeechRateLimitError("rate limited"), 503, "speech_rate_limited"),
        (SpeechRequestError("upstream failed"), 502, "speech_request_failed"),
        (SpeechAudioValidationError("invalid audio"), 500, "speech_audio_invalid"),
        (
            SpeechConfigurationError("profile/provider mismatch"),
            422,
            "speech_configuration_invalid",
        ),
    ],
)
def test_tts_errors_have_stable_codes(
    tmp_path: Path,
    error: Exception,
    status_code: int,
    error_code: str,
) -> None:
    app, store = _app(tmp_path, FailingNarrationService(error))
    project_id = uuid4()
    profile = _saved_profile(store, project_id)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/api/v1/narration/tts",
        json={
            "project_id": str(project_id),
            "script": "测试旁白",
            "speech_profile_id": str(profile.id),
        },
    )

    assert response.status_code == status_code
    assert response.json() == {
        "error": {"code": error_code, "message": str(error)}
    }


def test_missing_profile_has_stable_not_found_error(tmp_path: Path) -> None:
    app, _ = _app(tmp_path, FailingNarrationService(SpeechRequestError("unused")))
    client = TestClient(app)

    response = client.post(
        "/api/v1/narration/tts",
        json={
            "project_id": str(uuid4()),
            "script": "测试旁白",
            "speech_profile_id": str(uuid4()),
        },
    )

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "speech_profile_not_found",
            "message": "speech profile not found",
        }
    }


def test_missing_tts_runtime_has_stable_unavailable_error(tmp_path: Path) -> None:
    app, store = _app(tmp_path, None)
    project_id = uuid4()
    profile = _saved_profile(store, project_id)
    client = TestClient(app)

    response = client.post(
        "/api/v1/narration/tts",
        json={
            "project_id": str(project_id),
            "script": "测试旁白",
            "speech_profile_id": str(profile.id),
        },
    )

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "speech_provider_unavailable",
            "message": "TTS narration is not configured",
        }
    }

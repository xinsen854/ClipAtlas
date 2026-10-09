from pathlib import Path
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from clipatlas.api.routes.speech import router as speech_router
from clipatlas.speech.fake import FakeSpeechProvider
from clipatlas.speech.models import (
    NarrationSourceMode,
    NarrationTrack,
    NarrationUnit,
    SpeechProfile,
    TimingQuality,
)
from clipatlas.speech.registry import SpeechProviderRegistry
from clipatlas.speech.store import NarrationStore


class StubNarrationService:
    def __init__(self, store: NarrationStore) -> None:
        self.store = store

    async def create_tts_track(
        self,
        project_id: UUID,
        script: str,
        profile: SpeechProfile,
    ) -> NarrationTrack:
        track = NarrationTrack(
            project_id=project_id,
            source_mode=NarrationSourceMode.TTS,
            script_hash="stub-script",
            speech_profile_id=profile.id,
            provider=profile.provider,
            model=profile.model,
            audio_uri=(Path("/tmp/track.wav").resolve().as_uri()),
            duration_ms=1234,
            timing_quality=TimingQuality.UNIT_EXACT,
            revision=self.store.next_track_revision(project_id),
        )
        self.store.save_track(track)
        self.store.save_unit(
            NarrationUnit(
                track_id=track.id,
                sequence=0,
                text=script,
                text_hash="stub-unit",
                start_ms=0,
                end_ms=1234,
                audio_uri=Path("/tmp/unit.wav").resolve().as_uri(),
            )
        )
        self.store.activate_track(project_id, track.id)
        return track


class StubImportedNarrationService:
    def __init__(self, store: NarrationStore) -> None:
        self.store = store
        self.sources: list[Path] = []

    async def import_track(
        self,
        project_id: UUID,
        source_path: Path,
        script: str,
        aligner: object | None = None,
    ) -> NarrationTrack:
        self.sources.append(source_path)
        assert source_path.is_file()
        track = NarrationTrack(
            project_id=project_id,
            source_mode=NarrationSourceMode.IMPORTED,
            script_hash="stub-import",
            audio_uri=Path("/tmp/imported.wav").resolve().as_uri(),
            duration_ms=4321,
            timing_quality=TimingQuality.TRACK_ONLY,
            revision=self.store.next_track_revision(project_id),
        )
        self.store.save_track(track)
        self.store.save_unit(
            NarrationUnit(
                track_id=track.id,
                sequence=0,
                text=script,
                text_hash="stub-import-unit",
                source=NarrationSourceMode.IMPORTED,
            )
        )
        self.store.activate_track(project_id, track.id)
        return track


def build_test_app(tmp_path: Path) -> FastAPI:
    app = FastAPI()
    app.include_router(speech_router)
    registry = SpeechProviderRegistry()
    registry.register(FakeSpeechProvider())
    store = NarrationStore(tmp_path / "speech.sqlite3")
    app.state.speech_registry = registry
    app.state.narration_store = store
    app.state.narration_service = StubNarrationService(store)
    app.state.imported_narration_service = StubImportedNarrationService(store)
    app.state.narration_root = tmp_path / "narration"
    return app


def test_provider_and_voice_listing(tmp_path: Path) -> None:
    client = TestClient(build_test_app(tmp_path))

    providers = client.get("/api/v1/speech/providers")
    voices = client.get("/api/v1/speech/providers/fake/voices")

    assert providers.status_code == 200
    assert providers.json()[0]["name"] == "fake"
    assert voices.status_code == 200
    assert {item["voice_id"] for item in voices.json()} == {"fake-female", "fake-male"}
    assert client.get("/api/v1/speech/providers/missing/voices").status_code == 404


def test_randomize_profile_is_seeded_constrained_and_persisted(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    client = TestClient(app)
    project_id = uuid4()
    payload = {
        "project_id": str(project_id),
        "provider": "fake",
        "mode": "random_voice",
        "seed": 42,
        "constraints": {"gender": "female", "language": "zh-CN"},
    }

    first = client.post("/api/v1/speech/profiles/randomize", json=payload)
    second = client.post("/api/v1/speech/profiles/randomize", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["voice_id"] == "fake-female"
    assert second.json()["voice_id"] == "fake-female"
    stored = app.state.narration_store.get_profile(UUID(first.json()["id"]))
    assert stored is not None
    assert stored.random_seed == 42
    assert stored.locked is True


def test_tts_track_endpoint_returns_canonical_track_and_units(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    client = TestClient(app)
    project_id = uuid4()
    profile = SpeechProfile(
        project_id=project_id,
        provider="fake",
        model="fake-tts-v0.1",
        voice_id="fake-female",
        locked=True,
    )
    app.state.narration_store.save_profile(profile)

    response = client.post(
        "/api/v1/narration/tts",
        json={
            "project_id": str(project_id),
            "script": "测试旁白",
            "speech_profile_id": str(profile.id),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["track"]["duration_ms"] == 1234
    assert body["track"]["timing_quality"] == "unit_exact"
    assert body["units"][0]["start_ms"] == 0
    assert body["units"][0]["end_ms"] == 1234


def test_import_track_is_track_only_and_uses_controlled_temp_file(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    client = TestClient(app)
    project_id = uuid4()

    response = client.post(
        "/api/v1/narration/import",
        data={"project_id": str(project_id), "script": "真人旁白"},
        files={"file": ("voice.mp3", b"human-audio", "audio/mpeg")},
    )

    assert response.status_code == 200
    assert response.json()["track"]["timing_quality"] == "track_only"
    service = app.state.imported_narration_service
    assert len(service.sources) == 1
    assert str(service.sources[0]).startswith(str((tmp_path / "narration").resolve()))


def test_track_lookup_activation_and_unknown_track(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    client = TestClient(app)
    project_id = uuid4()
    track = NarrationTrack(
        project_id=project_id,
        source_mode=NarrationSourceMode.IMPORTED,
        script_hash="existing",
        audio_uri=Path("/tmp/existing.wav").resolve().as_uri(),
        duration_ms=1000,
        timing_quality=TimingQuality.TRACK_ONLY,
        revision=1,
    )
    app.state.narration_store.save_track(track)

    fetched = client.get(f"/api/v1/narration/{track.id}")
    activated = client.post(f"/api/v1/narration/{track.id}/activate")

    assert fetched.status_code == 200
    assert fetched.json()["track"]["id"] == str(track.id)
    assert activated.status_code == 200
    assert app.state.narration_store.get_active_track(project_id) == track
    assert client.get(f"/api/v1/narration/{uuid4()}").status_code == 404


def test_project_narration_history_lists_tracks_and_active_pointer(tmp_path: Path) -> None:
    app = build_test_app(tmp_path)
    client = TestClient(app)
    project_id = uuid4()
    first = NarrationTrack(
        project_id=project_id,
        source_mode=NarrationSourceMode.IMPORTED,
        script_hash="first",
        audio_uri=Path("/tmp/first.wav").resolve().as_uri(),
        duration_ms=1000,
        timing_quality=TimingQuality.TRACK_ONLY,
        revision=1,
    )
    second = NarrationTrack(
        project_id=project_id,
        source_mode=NarrationSourceMode.TTS,
        script_hash="second",
        provider="fake",
        model="fake-tts-v0.1",
        audio_uri=Path("/tmp/second.wav").resolve().as_uri(),
        duration_ms=1200,
        timing_quality=TimingQuality.UNIT_EXACT,
        revision=2,
    )
    app.state.narration_store.save_track(first)
    app.state.narration_store.save_track(second)
    app.state.narration_store.activate_track(project_id, first.id)

    response = client.get(f"/api/v1/projects/{project_id}/narrations")
    empty = client.get(f"/api/v1/projects/{uuid4()}/narrations")

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["tracks"]] == [str(second.id), str(first.id)]
    assert body["active_track_id"] == str(first.id)
    assert empty.status_code == 200
    assert empty.json() == {"tracks": [], "active_track_id": None}

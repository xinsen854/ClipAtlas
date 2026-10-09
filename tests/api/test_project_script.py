from hashlib import sha256
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from clipatlas.api.routes.speech import router
from clipatlas.projects.store import ProjectStore
from clipatlas.speech.audio import AudioNormalizer
from clipatlas.speech.importer import ImportedNarrationService
from clipatlas.speech.models import NarrationTrack, NarrationUnit
from clipatlas.speech.store import NarrationStore


def _app(tmp_path: Path):
    app = FastAPI()
    store = NarrationStore(tmp_path / "narration.sqlite3")
    projects = ProjectStore(tmp_path / "projects.sqlite3")
    project = projects.create("文案测试")
    app.state.project_store = projects
    app.state.narration_store = store
    app.state.imported_narration_service = ImportedNarrationService(
        store=store, audio_normalizer=AudioNormalizer(), narration_root=tmp_path / "audio",
    )
    app.include_router(router)
    return TestClient(app), store, project


def test_script_save_roundtrip_without_narration(tmp_path):
    client, store, project = _app(tmp_path)
    text = "原始文案\n 第二段，保留空格。"
    url = f"/api/v1/projects/{project.id}/script"
    assert client.get(url).json()["text"] == ""
    response = client.put(url, json={"text": text})
    assert response.status_code == 200 and response.json()["attached_track_id"] is None
    assert client.get(url).json()["text"] == text
    assert store.get_active_track(project.id) is None
    assert client.put(url, json={"text": "  "}).status_code == 422


def test_saved_script_rebinds_imported_audio_without_changing_past_revision(tmp_path):
    client, store, project = _app(tmp_path)
    audio = tmp_path / "真实音频.wav"
    audio.write_bytes(b"untouched audio fixture")
    old = NarrationTrack(project_id=project.id, source_mode="imported", script_hash="old",
                         audio_uri=audio.as_uri(), duration_ms=111305, timing_quality="aligned")
    store.save_track(old)
    store.save_unit(NarrationUnit(track_id=old.id, sequence=0, text="旧文案", text_hash="old"))
    store.activate_track(project.id, old.id)
    assert client.get(f"/api/v1/projects/{project.id}/script").json()["text"] == "旧文案"
    text = "保存的新文案。\n第二句。"
    response = client.put(f"/api/v1/projects/{project.id}/script", json={"text": text})
    assert response.status_code == 200
    active = store.get_active_track(project.id)
    assert str(active.id) == response.json()["attached_track_id"]
    assert active.id != old.id and active.revision == 2
    assert active.audio_uri == old.audio_uri and active.duration_ms == 111305
    assert active.timing_quality.value == "track_only"
    assert active.script_hash == sha256(text.encode()).hexdigest()
    assert client.get(f"/api/v1/narration/{active.id}").json()["script"] == text
    assert store.list_units(old.id)[0].text == "旧文案"
    assert audio.read_bytes() == b"untouched audio fixture"
    assert client.put(f"/api/v1/projects/{project.id}/script", json={"text": text}).json()["attached_track_id"] == str(active.id)


def test_changed_script_does_not_relabel_existing_tts_audio(tmp_path):
    client, store, project = _app(tmp_path)
    old = NarrationTrack(project_id=project.id, source_mode="tts", script_hash="old",
                         duration_ms=1000, timing_quality="unit_exact")
    store.save_track(old)
    store.activate_track(project.id, old.id)
    response = client.put(f"/api/v1/projects/{project.id}/script", json={"text": "新的配音文案"})
    assert response.status_code == 200 and response.json()["attached_track_id"] is None
    assert store.get_active_track(project.id).id == old.id

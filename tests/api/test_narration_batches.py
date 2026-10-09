import asyncio
import os
import sqlite3
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from clipatlas.api.errors import register_error_handlers
from clipatlas.api.routes.narration_batches import router
from clipatlas.domain.models import SemanticAnnotation
from clipatlas.projects.store import ProjectStore
from clipatlas.retrieval.search import SemanticSearchHit
from clipatlas.roughcut.planner import RoughCutPlanner
from clipatlas.roughcut.store import RoughCutStore
from clipatlas.speech.importer import ImportedNarrationService
from clipatlas.speech.models import NarrationTrack, TimingQuality
from clipatlas.speech.store import NarrationStore


class LocalAudioFixture:
    def __init__(self):
        self.calls = 0

    async def normalize(self, source, target, *, sample_rate):
        self.calls += 1
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())

    async def probe_duration_ms(self, path):
        return len(path.read_bytes()) * 1000


class RecordingSearch:
    def __init__(self):
        self.queries = []
        self.video_id = uuid4()

    def project_video_ids(self, project_id):
        return [self.video_id]

    async def search(self, query, *, limit, video_ids=None):
        self.queries.append(query)
        segment_id = uuid4()
        return [SemanticSearchHit(
            segment_id=segment_id, video_id=self.video_id, source_uri="file:///fixture.mp4",
            source_start_ms=1000, source_end_ms=10000, score=0.9,
            effective_description="fixture", annotation=SemanticAnnotation(
                segment_id=segment_id, origin="ai", description="fixture", confidence=0.9,
            ), embedding_provider="fixture", embedding_model="fixture", embedding_dimensions=1,
        )]


class FixtureAlignment:
    def __init__(self, store):
        self.store = store

    async def ensure_aligned(self, track):
        aligned = track.model_copy(update={"id": uuid4(), "timing_quality": TimingQuality.ALIGNED,
                                           "alignment_source_id": track.id})
        units = [u.model_copy(update={"id": uuid4(), "track_id": aligned.id,
                                      "start_ms": 0, "end_ms": track.duration_ms})
                 for u in self.store.list_units(track.id)]
        self.store.save_track_snapshot(aligned, units)
        return aligned


def setup(tmp_path: Path):
    projects = ProjectStore(tmp_path / "projects.sqlite3")
    project = projects.create("批量测试")
    store = NarrationStore(tmp_path / "narration.sqlite3")
    plans = RoughCutStore(tmp_path / "plans.sqlite3")
    audio = LocalAudioFixture()
    search = RecordingSearch()
    active = NarrationTrack(project_id=project.id, source_mode="imported", duration_ms=7000,
                            script_hash=sha256("单条文案".encode()).hexdigest(), timing_quality="track_only")
    store.save_track(active)
    store.activate_track(project.id, active.id)
    store.save_project_script(project.id, "单条文案")
    app = FastAPI()
    app.state.project_store = projects
    app.state.narration_store = store
    app.state.narration_root = tmp_path / "audio"
    app.state.imported_narration_service = ImportedNarrationService(
        store=store, audio_normalizer=audio, narration_root=app.state.narration_root,
    )
    app.state.rough_cut_store = plans
    app.state.rough_cut_planner = RoughCutPlanner(narration_store=store, search=search, store=plans,
                                                alignment_service=FixtureAlignment(store))
    app.state.narration_batch_lock = asyncio.Lock()
    app.include_router(router)
    register_error_handlers(app)
    return TestClient(app), store, plans, project, active, audio, search


def create_payload():
    return {
        "name": "两条文案", "markdown": "## 001 标题甲\n甲文案。\n## 002 标题乙\n乙文案。",
        "files": [{"name": "002.wav", "size": 2}, {"name": "001.wav", "size": 1}],
        "assignments": [{"entry_id": "entry-001", "audio_index": 1}, {"entry_id": "entry-002", "audio_index": 0}],
        "confirm": "MATCHES_CONFIRMED",
    }


def test_preview_recognizes_user_three_scripts_without_upload_or_model_calls(tmp_path):
    client, store, _, project, active, audio, search = setup(tmp_path)
    markdown = (Path(__file__).resolve().parents[1]/'fixtures/batch-three-numbered.md').read_text(encoding='utf-8')
    result = client.post(f'/api/v1/projects/{project.id}/narration-batches/preview',
                         json={'markdown':markdown,'files':[]})
    assert result.status_code == 200
    rows = result.json()
    assert len(rows) == 3 and [row['script']['code'] for row in rows] == ['001','002','003']
    assert all(row['audio_index'] is None for row in rows)
    assert '第一道是性能' in rows[2]['script']['text']
    assert '本身就是对产品成色最直接的确认。' in rows[2]['script']['text']
    assert store.list_batches(project.id) == [] and audio.calls == 0 and search.queries == []
    assert store.get_active_track(project.id).id == active.id


def test_two_entries_import_and_plan_use_their_own_snapshots_and_are_resumable(tmp_path):
    client, store, plans, project, active, audio, search = setup(tmp_path)
    base = f"/api/v1/projects/{project.id}/narration-batches"
    payload = create_payload()
    before = client.post(base + "/preview", json={"markdown": payload["markdown"], "files": payload["files"]})
    assert [m["audio_index"] for m in before.json()] == [1, 0]
    assert store.list_batches(project.id) == [] and audio.calls == 0
    created = client.post(base, json=payload)
    assert created.status_code == 201
    batch_id = created.json()["id"]
    expected = [("entry-001", "001.wav", b"a", "甲文案。"), ("entry-002", "002.wav", b"bb", "乙文案。")]
    for entry_id, filename, data, text in expected:
        uri = f"{base}/{batch_id}/entries/{entry_id}"
        result = client.post(uri + "/audio", files={"file": (filename, data, "audio/wav")})
        assert result.status_code == 200 and result.json()["script"] == text
        assert result.json()["track"]["duration_ms"] == len(data) * 1000
        duplicate = client.post(uri + "/audio", files={"file": (filename, data, "audio/wav")})
        assert duplicate.json()["track"]["id"] == result.json()["track"]["id"]
        assert client.post(uri + "/plan", json={}).status_code == 422
        plan = client.post(uri + "/plan", json={"confirm": "GENERATE_ROUGH_CUT"})
        assert plan.status_code == 200
        planned_track = store.get_track(UUID(plan.json()["narration_track_id"]))
        assert planned_track.id == UUID(result.json()["track"]["id"])
        assert planned_track.timing_quality == TimingQuality.TRACK_ONLY
        assert any("本地文本权重估算" in warning for warning in plan.json()["warnings"])
        assert plan.json()["total_duration_ms"] == len(data) * 1000
        assert plan.json()["beats"][0]["text"] == text
        retry = client.post(uri + "/plan", json={"confirm": "GENERATE_ROUGH_CUT"})
        assert retry.json()["id"] == plan.json()["id"]
    assert audio.calls == 2 and search.queries == ["甲文案。", "乙文案。"]
    assert store.get_active_track(project.id).id == active.id
    assert store.get_project_script(project.id).text == "单条文案"
    assert plans.get_active_plan(project.id) is None
    reopened = NarrationStore(tmp_path / "narration.sqlite3").get_batch(UUID(batch_id))
    assert all(entry.plan_id and entry.narration_track_id for entry in reopened.entries)


def test_missing_conflicting_and_cross_project_assignments_are_rejected(tmp_path):
    client, _, _, project, _, audio, _ = setup(tmp_path)
    base = f"/api/v1/projects/{project.id}/narration-batches"
    payload = create_payload()
    bad = {**payload, "assignments": [{"entry_id": "entry-001", "audio_index": 0}, {"entry_id": "entry-002", "audio_index": 0}]}
    assert client.post(base, json=bad).status_code == 422
    assert client.post(base, json={**payload, "assignments": []}).status_code == 422
    batch = client.post(base, json=payload).json()
    wrong = client.post(f"{base}/{batch['id']}/entries/entry-001/audio", files={"file": ("002.wav", b"a")})
    assert wrong.status_code == 422 and audio.calls == 0
    assert client.get(f"/api/v1/projects/{uuid4()}/narration-batches/{batch['id']}").status_code == 404


def test_retry_repairs_an_interrupted_import_without_changing_its_track_id(tmp_path):
    client, store, _, project, _, audio, _ = setup(tmp_path)
    base = f"/api/v1/projects/{project.id}/narration-batches"
    created = client.post(base, json=create_payload()).json()
    uri = f"{base}/{created['id']}/entries/entry-001/audio"
    first = client.post(uri, files={"file": ("001.wav", b"a")}).json()
    track_id = first['track']['id']
    # Simulate interruption after track persistence but before unit/batch persistence.
    with sqlite3.connect(tmp_path / 'narration.sqlite3') as connection:
        connection.execute('DELETE FROM narration_units WHERE track_id=?', (track_id,))
    batch = store.get_batch(UUID(created['id']))
    batch.entries[0].narration_track_id = None
    store.save_batch(batch)
    repaired = client.post(uri, files={"file": ("001.wav", b"a")})
    assert repaired.status_code == 200
    assert repaired.json()['track']['id'] == track_id
    assert repaired.json()['units'][0]['text'] == '甲文案。'
    assert audio.calls == 2
    changed = client.post(uri, files={"file": ("001.wav", b"x")})
    assert changed.status_code == 422 and audio.calls == 2


def test_batch_routes_and_operation_lock_are_injected_into_application(tmp_path, monkeypatch):
    for key in list(os.environ):
        if key.startswith("CLIPATLAS_") or key == "DASHSCOPE_API_KEY":
            monkeypatch.delenv(key, raising=False)
    for key, filename in {
        "SETTINGS_FILE": "settings.json", "PROJECT_DB": "projects.sqlite3",
        "PROJECT_RULE_DB": "rules.sqlite3", "LIBRARY_DB": "library.sqlite3",
        "NARRATION_ROOT": "narration", "ROUGHCUT_DB": "roughcut.sqlite3",
        "LIBRARY_CACHE_ROOT": "cache", "VIDEO_ROOT": "videos", "EXPORT_ROOT": "exports",
    }.items():
        monkeypatch.setenv("CLIPATLAS_" + key, str(tmp_path / filename))
    from clipatlas.main import create_app

    app = create_app()
    assert isinstance(app.state.narration_batch_lock, asyncio.Lock)
    client = TestClient(app)
    project = client.post('/api/v1/projects', json={'name': 'offline batch runtime'}).json()
    response = client.post(
        f"/api/v1/projects/{project['id']}/narration-batches/preview",
        json={'markdown': '## 001 测试\n离线正文', 'files': [{'name': '001.wav', 'size': 1}]},
    )
    assert response.status_code == 200 and response.json()[0]['audio_index'] == 0

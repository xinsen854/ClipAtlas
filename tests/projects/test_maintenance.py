import json
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from clipatlas.projects.maintenance import ProjectMaintenance
from clipatlas.projects.store import ProjectStore
from clipatlas.roughcut.store import RoughCutStore
from clipatlas.rules.store import ProjectRuleStore
from clipatlas.speech.models import NarrationTrack, NarrationUnit, NarrationWordTiming
from clipatlas.speech.store import NarrationStore


@pytest.fixture
def project_data(tmp_path):
    projects = ProjectStore(tmp_path/'projects.sqlite3')
    speech = NarrationStore(tmp_path/'narration.sqlite3')
    plans = RoughCutStore(tmp_path/'roughcut.sqlite3')
    rules = ProjectRuleStore(tmp_path/'rules.sqlite3')
    root, exports = tmp_path/'audio', tmp_path/'exports'
    a, b = projects.create('A'), projects.create('B')
    tracks = []
    for project in [a,b]:
        tid = uuid4()
        audio = root/str(project.id)/str(tid)/'track.wav'
        audio.parent.mkdir(parents=True)
        audio.write_bytes(project.name.encode())
        track = NarrationTrack(id=tid, project_id=project.id, source_mode='imported',
            script_hash='text', script='文案', duration_ms=1000, timing_quality='track_only',
            audio_uri=audio.as_uri())
        speech.save_track(track)
        unit = NarrationUnit(track_id=tid, sequence=0, text='文案', text_hash='text', start_ms=0, end_ms=1000)
        speech.save_unit(unit)
        speech.save_word_timings([NarrationWordTiming(unit_id=unit.id, sequence=0, word='文案', start_ms=0, end_ms=1000)])
        speech.activate_track(project.id, tid)
        speech.save_project_script(project.id, '文案')
        with sqlite3.connect(speech._db_path) as c:
            c.execute('INSERT INTO narration_batches VALUES (?,?,?,?)',(str(uuid4()),str(project.id),'now','{}'))
        rules.save_draft(project.id, [])
        pid = str(uuid4())
        with sqlite3.connect(plans._db_path) as c:
            c.execute('INSERT INTO rough_cut_plans VALUES (?,?,1,?,?)',(pid,str(project.id),'now','{}'))
            c.execute('INSERT INTO active_rough_cut_plans VALUES (?,?)',(str(project.id),pid))
        output = exports/str(project.id)/pid/'draft.otio'
        output.parent.mkdir(parents=True)
        output.write_text('output')
        tracks.append(track)
    library = tmp_path/'shared-cache'
    library.mkdir()
    (library/'frame.jpg').write_bytes(b'keep shared')
    service = ProjectMaintenance(project_db=projects._db_path,narration_db=speech._db_path,
        roughcut_db=plans._db_path,rules_db=rules._db_path,narration_root=root,export_root=exports)
    return service, projects, speech, a, b, tracks, library


def test_deletion_removes_owned_rows_files_and_preserves_other_project_and_shared_cache(project_data):
    service, projects, speech, a, b, tracks, library = project_data
    preview = service.preview(a.id)
    assert preview.narrations == preview.plans == preview.batches == 1
    assert len(preview.directories) == 2
    result = service.delete(a.id)
    assert projects.get(a.id) is None and projects.get(b.id) is not None
    assert not (service.narration_root/str(a.id)).exists()
    assert not (service.export_root/str(a.id)).exists()
    assert (service.narration_root/str(b.id)/str(tracks[1].id)/'track.wav').read_bytes() == b'B'
    assert (library/'frame.jpg').read_bytes() == b'keep shared'
    assert speech.get_track(tracks[0].id) is None
    assert speech.get_track(tracks[1].id) is not None
    for path in set(service.databases.values()):
        with sqlite3.connect(path) as c:
            assert not c.execute('PRAGMA foreign_key_check').fetchall()
    assert len(list(Path(result.backup_directory).glob('*.sqlite3'))) == 4


def test_other_project_audio_reference_is_retained(project_data):
    service, projects, speech, a, b, tracks, _ = project_data
    shared = tracks[1].model_copy(update={'audio_uri':tracks[0].audio_uri})
    speech.save_track(shared)
    result = service.delete(a.id)
    assert result.warnings
    assert (service.narration_root/str(a.id)/str(tracks[0].id)/'track.wav').exists()
    assert speech.get_track(tracks[1].id).audio_uri == tracks[0].audio_uri


def test_database_failure_rolls_back_rows_and_directory_moves(project_data):
    service, projects, speech, a, _, tracks, _ = project_data
    with sqlite3.connect(service.databases['rules']) as c:
        c.execute("CREATE TRIGGER prevent_delete BEFORE DELETE ON project_rule_packs BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match='fixture failure'):
        service.delete(a.id)
    assert projects.get(a.id) is not None
    assert speech.get_track(tracks[0].id) is not None
    assert (service.narration_root/str(a.id)/str(tracks[0].id)/'track.wav').exists()
    assert not list(service.narration_root.glob('.delete-project-*'))


def test_symlink_in_project_directory_fails_before_deletion(project_data, tmp_path):
    service, projects, _, a, _, _, _ = project_data
    private = tmp_path/'private'
    private.mkdir()
    (private/'keep').write_text('private')
    link = service.narration_root/str(a.id)/'linked'
    try:
        link.symlink_to(private, target_is_directory=True)
    except OSError:
        pytest.skip('Windows symlink creation unavailable')
    with pytest.raises(ValueError, match='link|junction'):
        service.delete(a.id)
    assert projects.get(a.id) is not None and (private/'keep').exists()


def test_project_delete_api_requires_confirmation(project_data):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from clipatlas.api.routes.projects import router
    from clipatlas.api.maintenance import install_maintenance_gate
    service, projects, _, a, b, _, _ = project_data
    app=FastAPI()
    install_maintenance_gate(app)
    app.state.project_store=projects
    app.state.project_maintenance=service
    app.include_router(router)
    client=TestClient(app)
    assert client.get(f'/api/v1/projects/{a.id}/deletion-preview').json()['name']=='A'
    assert client.request('DELETE',f'/api/v1/projects/{a.id}',json={}).status_code==422
    assert projects.get(a.id) is not None
    result=client.request('DELETE',f'/api/v1/projects/{a.id}',json={'confirm':'DELETE_PROJECT'})
    assert result.status_code==200 and result.json()['name']=='A'
    assert client.get(f'/api/v1/projects/{a.id}').status_code==404
    assert client.get(f'/api/v1/projects/{b.id}').status_code==200

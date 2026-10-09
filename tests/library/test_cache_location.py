import sqlite3
import asyncio
import threading
from types import SimpleNamespace
from uuid import uuid4

import pytest

from clipatlas.catalog.store import CatalogStore
from clipatlas.library.cache_location import move_library_cache
from clipatlas.library.store import LibraryStore
from clipatlas.settings.store import SettingsStore


@pytest.fixture
def cache_data(tmp_path):
    db=tmp_path/'library.sqlite3'
    CatalogStore(db)
    LibraryStore(db)
    old=tmp_path/'old-cache'
    old.mkdir()
    frame=old/'frames'/'a b.jpg'
    frame.parent.mkdir()
    frame.write_bytes(b'cached frame')
    (old/'video-chunks').mkdir()
    (old/'video-chunks'/'clip.mp4').write_bytes(b'cached clip')
    video,segment=str(uuid4()),str(uuid4())
    source=tmp_path/'original.mp4'
    source.write_bytes(b'original')
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO catalog_videos (id, filename, source_uri, duration_ms, width, height, fps, video_codec, has_audio, created_at) VALUES (?, 'v.mp4', ?, 1000, 10, 10, 1, 'h264', 1, '2026-09-06T00:00:00+00:00')",(video,source.as_uri()))
        c.execute("INSERT INTO catalog_segments VALUES (?,?,0,1000,'scene_detection','2026-09-06T00:00:00+00:00')",(segment,video))
        c.execute('INSERT INTO catalog_segment_frames VALUES (?,0,?)',(segment,frame.as_uri()))
    settings=SettingsStore(tmp_path/'settings.json',environment={})
    return db,old,settings,source


def test_move_keeps_indexes_updates_frame_uri_and_preserves_original(cache_data,tmp_path):
    db,old,settings,source=cache_data
    target=tmp_path/'new cache'
    result=move_library_cache(db,old,target,settings)
    assert result.restart_required and result.files_moved==2
    assert not old.exists()
    assert (target/'frames'/'a b.jpg').read_bytes()==b'cached frame'
    assert source.read_bytes()==b'original'
    with sqlite3.connect(db) as c:
        assert c.execute('SELECT uri FROM catalog_segment_frames').fetchone()[0]==(target/'frames'/'a b.jpg').as_uri()
        assert c.execute('SELECT count(*) FROM catalog_videos').fetchone()[0]==1
        assert not c.execute('PRAGMA foreign_key_check').fetchall()
    assert settings.read_persisted().library_cache_root==str(target)


def test_failed_settings_save_rolls_back_database_and_keeps_original_cache(cache_data,tmp_path,monkeypatch):
    db,old,settings,_=cache_data
    def fail(patch):raise OSError('fixture config failure')
    monkeypatch.setattr(settings,'update',fail)
    with pytest.raises(OSError,match='fixture config failure'):
        move_library_cache(db,old,tmp_path/'new',settings)
    assert (old/'frames'/'a b.jpg').exists()
    assert not (tmp_path/'new').exists()
    with sqlite3.connect(db) as c:
        assert c.execute('SELECT uri FROM catalog_segment_frames').fetchone()[0]==(old/'frames'/'a b.jpg').as_uri()


def test_move_rejects_nonempty_nested_or_root_destinations(cache_data,tmp_path):
    db,old,settings,_=cache_data
    occupied=tmp_path/'occupied'
    occupied.mkdir()
    (occupied/'user-file').write_text('keep')
    for target in [occupied,old/'nested',tmp_path,tmp_path.anchor]:
        from pathlib import Path
        with pytest.raises(ValueError):move_library_cache(db,old,Path(target),settings)
    assert (occupied/'user-file').exists() and (old/'frames'/'a b.jpg').exists()


def test_migration_api_keeps_thumbnails_readable_and_blocks_parsing_until_restart(cache_data,tmp_path,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from clipatlas.api.routes.library import router
    from clipatlas.api.routes.index_results import router as results_router
    from clipatlas.api.maintenance import install_maintenance_gate
    from clipatlas.library.maintenance import LibraryMaintenance
    from clipatlas.settings.models import SettingsPatch
    db,old,_,_=cache_data
    monkeypatch.setenv('CLIPATLAS_LIBRARY_CACHE_ROOT',str(old))
    settings=SettingsStore(tmp_path/'actual-settings.json')
    settings.update(SettingsPatch(library_cache_root=str(old)))
    settings._inject_compatibility_value('CLIPATLAS_LIBRARY_CACHE_ROOT',str(old),force=True)
    app=FastAPI()
    install_maintenance_gate(app)
    app.state.settings_store=settings
    app.state.library_store=LibraryStore(db)
    app.state.library_catalog=CatalogStore(db)
    app.state.library_maintenance=LibraryMaintenance(db,old)
    app.state.library_worker=SimpleNamespace(operation_lock=asyncio.Lock())
    app.state.library_supervisor=SimpleNamespace(processing_available=True,paused=True,pause=lambda:None,resume=lambda:True)
    app.include_router(router)
    app.include_router(results_router)
    client=TestClient(app)
    target=tmp_path/'new-cache'
    response=client.post('/api/v1/library/cache-location',json={'path':str(target),'confirm':'MOVE_LIBRARY_CACHE'})
    assert response.status_code==200,response.text
    assert client.get('/api/v1/library/cache-location').json()['path']==str(target)
    assert client.post('/api/v1/library/processing/resume').status_code==409
    with sqlite3.connect(db) as c:video=c.execute('SELECT id FROM catalog_videos').fetchone()[0]
    thumbnail=client.get(f'/api/v1/videos/{video}/index-thumbnail?timestamp_ms=0')
    assert thumbnail.status_code==200 and thumbnail.content==b'cached frame'


@pytest.mark.asyncio
async def test_client_disconnect_still_sets_restart_guard_after_successful_migration(cache_data,tmp_path,monkeypatch):
    from clipatlas.api.routes import library as routes
    from clipatlas.library.cache_location import CacheMoveResult
    db,old,settings,_=cache_data
    started,release=threading.Event(),threading.Event()
    def move(*args):
        started.set()
        release.wait(3)
        return CacheMoveResult(previous_path=str(old),path=str(tmp_path/'new'),files_moved=1,restart_required=True)
    monkeypatch.setattr(routes,'move_library_cache',move)
    state=SimpleNamespace(library_worker=SimpleNamespace(operation_lock=asyncio.Lock()),settings_store=settings,
        library_maintenance=SimpleNamespace(db_path=db,cache_root=old),cache_restart_required=False,
        library_supervisor=SimpleNamespace(processing_available=True,paused=True,pause=lambda:None,resume=lambda:True))
    request=SimpleNamespace(app=SimpleNamespace(state=state))
    task=asyncio.create_task(routes.change_cache_location(request,routes.CacheLocationRequest(path=str(tmp_path/'new'),confirm='MOVE_LIBRARY_CACHE')))
    while not started.is_set():await asyncio.sleep(.001)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):await task
    assert state.cache_restart_required and not state.library_worker.operation_lock.locked()


@pytest.mark.asyncio
async def test_invalid_cache_destination_restores_previous_processing_state(cache_data,tmp_path):
    from fastapi import HTTPException
    from clipatlas.api.routes import library as routes
    db,old,settings,_=cache_data
    occupied=tmp_path/'occupied'
    occupied.mkdir()
    (occupied/'keep').write_text('keep')
    calls=[]
    state=SimpleNamespace(library_worker=SimpleNamespace(operation_lock=asyncio.Lock()),settings_store=settings,
        library_maintenance=SimpleNamespace(db_path=db,cache_root=old),cache_restart_required=False,
        library_supervisor=SimpleNamespace(processing_available=True,paused=False,
            pause=lambda:calls.append('pause'),resume=lambda:calls.append('resume')))
    request=SimpleNamespace(app=SimpleNamespace(state=state))
    with pytest.raises(HTTPException):
        await routes.change_cache_location(request,routes.CacheLocationRequest(path=str(occupied),confirm='MOVE_LIBRARY_CACHE'))
    assert calls==['pause','resume'] and (occupied/'keep').exists()

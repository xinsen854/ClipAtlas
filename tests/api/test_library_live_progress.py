import hashlib
import sqlite3
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from clipatlas.api.routes.library import router
from clipatlas.asr.models import ASRChunkRecord
from clipatlas.asr.store import ASRStore
from clipatlas.catalog.checkpoints import PreparedMediaCheckpointStore, VideoChunkCheckpointStore
from clipatlas.catalog.store import CatalogStore
from clipatlas.library.index_progress import LibraryIndexProgressReader
from clipatlas.library.models import LibraryItemStatus
from clipatlas.library.store import LibraryStore
from clipatlas.ocr.models import OCRSampleRecord
from clipatlas.ocr.store import OCRStore


def setup(tmp_path):
    db = tmp_path / 'library.sqlite3'
    store = LibraryStore(db)
    CatalogStore(db)
    checkpoints = PreparedMediaCheckpointStore(db)
    visual = VideoChunkCheckpointStore(db)
    asr, ocr = ASRStore(db), OCRStore(db)
    source = tmp_path / 'movie.mp4'
    source.write_bytes(b'fixture')
    root = store.add_root(tmp_path)
    store.save_observation(root.id, source, 7, 1, 'current-fingerprint')
    item = store.get_item_by_path(source)
    video_id = uuid4()
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO catalog_videos (id, filename, source_uri, duration_ms, width, height, fps, video_codec, has_audio, created_at) VALUES (?, 'movie.mp4', ?, 10000, 64, 64, 10, "
                  "'h264', 1, '2026-09-06T00:00:00+00:00')", (str(video_id), source.as_uri()))
    checkpoints.save(item.id, item.fingerprint, video_id)
    for start, end in [(0,5000), (4000,9000), (8000,10000)]:
        visual.mark_completed(video_id, start, end, 'qwen-vl-video', 'qwen3-vl-embedding')
    asr.save_asr_chunk(ASRChunkRecord(
        video_id=video_id, start_ms=0, end_ms=10000, provider='bailian-asr',
        model='qwen-audio-3.0-asr-flash', revision=1, status='processing', attempt_count=1,
    ))
    store.set_status(item.id, LibraryItemStatus.FRAME_EXTRACTION)
    app = FastAPI()
    app.state.library_store = store
    app.state.library_index_progress = LibraryIndexProgressReader(
        db, visual_enabled=True, asr_enabled=True, ocr_interval_ms=5000,
    )
    app.include_router(router)
    return TestClient(app), db, store, item, video_id, asr, ocr


def test_inflight_detail_exposes_prepared_video_and_live_stage_without_writes(tmp_path):
    client, db, store, item, video_id, asr, ocr = setup(tmp_path)
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    url = f'/api/v1/library/items/{item.id}'
    response = client.get(url)
    assert response.status_code == 200
    body = response.json()
    assert body['video_id'] is None
    assert body['prepared_video_id'] == str(video_id)
    assert body['processing_stage'] == 'asr'
    assert body['index_progress']['visual']['completed'] == 3
    assert body['index_progress']['asr']['processing'] == 1
    assert body['progress_updated_at'] is not None
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before
    asr.save_asr_chunk(ASRChunkRecord(
        video_id=video_id, start_ms=0, end_ms=10000, provider='bailian-asr',
        model='qwen-audio-3.0-asr-flash', revision=1, status='completed', attempt_count=1,
    ))
    ocr.save_sample(OCRSampleRecord(
        video_id=video_id, start_ms=0, end_ms=5000, interval_ms=5000, provider='bailian-ocr',
        model='qwen3.5-ocr', revision=1, status='processing', attempt_count=1,
    ))
    assert client.get(url).json()['processing_stage'] == 'ocr'
    store.fail(item.id, 'fixture failure')
    failed = client.get(url).json()
    assert failed['processing_stage'] is None and failed['status'] == 'FAILED'
    assert failed['prepared_video_id'] == str(video_id)


def test_changed_fingerprint_never_displays_previous_preparation(tmp_path):
    client, _, store, item, _, _, _ = setup(tmp_path)
    store.save_observation(item.root_id, tmp_path/'movie.mp4', 8, 2, 'changed-fingerprint')
    body = client.get(f'/api/v1/library/items/{item.id}').json()
    assert body['prepared_video_id'] is None and body['index_progress'] is None


def test_detail_lists_all_parallel_stages(tmp_path):
    client, db, _, item, video_id, _, ocr = setup(tmp_path)
    visual = VideoChunkCheckpointStore(db)
    visual.mark_processing(video_id, 0, 5000, 'qwen-vl-video', 'qwen3-vl-embedding')
    ocr.save_sample(OCRSampleRecord(
        video_id=video_id, start_ms=0, end_ms=5000, interval_ms=5000,
        provider='bailian-ocr', model='qwen3.5-ocr', revision=1,
        status='processing', attempt_count=1,
    ))
    body = client.get(f'/api/v1/library/items/{item.id}').json()
    assert body['processing_stages'] == ['visual', 'asr', 'ocr']
    assert all(body['index_progress'][stage]['processing'] == 1
               for stage in body['processing_stages'])

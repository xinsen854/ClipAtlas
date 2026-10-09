import asyncio
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from clipatlas.asr.store import ASRStore
from clipatlas.catalog.checkpoints import PreparedMediaCheckpointStore, VideoChunkCheckpointStore
from clipatlas.catalog.store import CatalogStore
from clipatlas.domain.models import SemanticAnnotation
from clipatlas.library.maintenance import LibraryMaintenance
from clipatlas.library.store import LibraryStore
from clipatlas.library.worker import SequentialLibraryWorker
from clipatlas.ocr.store import OCRStore
from clipatlas.retrieval.models import SegmentEmbedding


@pytest.fixture
def library(tmp_path):
    db = tmp_path / "library.sqlite3"
    store = LibraryStore(db)
    catalog = CatalogStore(db)
    ASRStore(db)
    OCRStore(db)
    PreparedMediaCheckpointStore(db)
    VideoChunkCheckpointStore(db)
    source = tmp_path / "素材 原片.mp4"
    source.write_bytes(b"original media")
    root = store.add_root(tmp_path)
    store.save_observation(root_id=root.id, source_path=source, size_bytes=14,
                           mtime_ns=1, fingerprint="v1")
    item = store.list_items()[0]
    video_id = uuid4()
    segment_id = uuid4()
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO catalog_videos (id, filename, source_uri, duration_ms, width, height, fps, video_codec, has_audio, created_at) VALUES (?, 'source.mp4', ?, 1000, 64, 64, 10, "
                  "'h264', 1, '2026-09-06T00:00:00+00:00')", (str(video_id), source.as_uri()))
        c.execute("INSERT INTO catalog_segments VALUES (?, ?, 0, 1000, 'scene_detection', "
                  "'2026-09-06T00:00:00+00:00')", (str(segment_id), str(video_id)))
    annotation = SemanticAnnotation(segment_id=segment_id, origin="human", description="保留到用户确认清空")
    catalog.save_annotation(annotation)
    catalog.save_embedding(SegmentEmbedding(
        segment_id=segment_id, annotation_id=annotation.id, annotation_revision=1,
        provider="test", model="test", dimensions=1, vector=[1.0],
    ))
    store.complete(item.id, video_id)
    cache = tmp_path / "cache"
    files = []
    for directory in [cache / "video-chunks", cache / "asr", cache / "ocr",
                      cache / str(item.id) / "frames"]:
        directory.mkdir(parents=True)
        f = directory / "fixture.bin"
        f.write_bytes(b"cached analysis")
        files.append(f)
    return db, store, item, source, files, LibraryMaintenance(db, cache)


def test_reset_clears_derived_rows_and_cache_but_preserves_source_and_roots(library):
    db, store, item, source, files, maintenance = library
    result = maintenance.reset_analysis()
    assert result.items_reset == 1 and result.cache_directories_removed == 4
    assert Path(result.backup_path).is_file()
    assert source.read_bytes() == b"original media"
    assert all(not f.exists() for f in files)
    reset = store.get_item(item.id)
    assert reset.status.value == "QUEUED" and reset.video_id is None and reset.attempts == 0
    assert len(store.list_roots()) == 1
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT count(*) FROM catalog_videos").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM catalog_annotations").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM catalog_embeddings").fetchone()[0] == 0
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
    with sqlite3.connect(result.backup_path) as c:
        assert c.execute("SELECT count(*) FROM catalog_videos").fetchone()[0] == 1


def test_reset_restores_files_and_rows_if_database_transaction_fails(library):
    db, store, item, source, files, maintenance = library
    with sqlite3.connect(db) as c:
        c.execute("CREATE TRIGGER deny_reset BEFORE DELETE ON catalog_videos "
                  "BEGIN SELECT RAISE(ABORT, 'rollback fixture'); END")
    with pytest.raises(sqlite3.IntegrityError, match="rollback fixture"):
        maintenance.reset_analysis()
    assert store.get_item(item.id).status.value == "COMPLETED"
    assert all(f.read_bytes() == b"cached analysis" for f in files)
    assert source.read_bytes() == b"original media"


def test_reset_refuses_cache_containing_source_media(library):
    db, _, item, source, files, maintenance = library
    with sqlite3.connect(db) as c:
        c.execute("UPDATE library_items SET source_path=? WHERE id=?", (str(files[0]), str(item.id)))
    with pytest.raises(ValueError, match="source-media"):
        maintenance.reset_analysis()
    assert all(f.exists() for f in files) and source.exists()


def test_reset_refuses_inflight_item(library):
    db, _, _, _, files, maintenance = library
    with sqlite3.connect(db) as c:
        c.execute("UPDATE library_items SET status='PROBING'")
    with pytest.raises(ValueError, match="still being processed"):
        maintenance.reset_analysis()
    assert all(f.exists() for f in files)


@pytest.mark.asyncio
async def test_explicit_reparse_forces_visual_and_rejects_concurrent_operations(library):
    db, store, item, _, _, _ = library
    catalog = CatalogStore(db)
    prepared = catalog.get_ingested_video(store.get_item(item.id).video_id)
    visual = SimpleNamespace(index_video=AsyncMock())
    worker = SequentialLibraryWorker(
        store, SimpleNamespace(prepare=AsyncMock(return_value=prepared)),
        catalog=catalog, video_indexer=visual,
    )
    assert await worker.reparse_item(item.id)
    assert visual.index_video.call_args.kwargs == {"force": True}
    async with worker.operation_lock:
        assert not await worker.reparse_item(item.id)


def test_reset_endpoint_requires_confirmation_and_refuses_busy_worker():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from clipatlas.api.routes.library import router

    app = FastAPI()
    lock = asyncio.Lock()
    asyncio.run(lock.acquire())
    app.state.library_worker = SimpleNamespace(operation_lock=lock)
    app.include_router(router)
    client = TestClient(app)
    assert client.post('/api/v1/library/reset-analysis', json={}).status_code == 422
    assert client.post('/api/v1/library/reset-analysis', json={
        'confirm': 'CLEAR_ALL_LIBRARY_ANALYSIS',
    }).status_code == 409

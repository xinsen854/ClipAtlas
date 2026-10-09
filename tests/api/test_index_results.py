import base64
import hashlib
import sqlite3
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from clipatlas.api.routes.index_results import readable_ocr_text, router
from clipatlas.asr.models import ASRChunkRecord, ASRSentence
from clipatlas.asr.store import ASRStore
from clipatlas.catalog.checkpoints import VideoChunkCheckpointStore
from clipatlas.catalog.store import CatalogStore
from clipatlas.domain.models import AnnotationOrigin, SemanticAnnotation
from clipatlas.ocr.models import OCRSampleRecord
from clipatlas.ocr.store import OCRStore


@pytest.fixture
def indexed_video(tmp_path, monkeypatch):
    db = tmp_path / "library.sqlite3"
    catalog, asr, ocr = CatalogStore(db), ASRStore(db), OCRStore(db)
    VideoChunkCheckpointStore(db)
    video_id, other_id, segment_id = uuid4(), uuid4(), uuid4()
    root = tmp_path / "cache"
    root.mkdir()
    frame = root / "frame.png"
    frame.write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aDe8AAAAASUVORK5CYII="
    ))
    monkeypatch.setenv("CLIPATLAS_LIBRARY_CACHE_ROOT", str(root))
    with sqlite3.connect(db) as c:
        for vid in (video_id, other_id):
            c.execute(
                "INSERT INTO catalog_videos (id, filename, source_uri, duration_ms, width, height, fps, video_codec, has_audio, created_at) VALUES (?, 'sample.mp4', 'file:///sample.mp4', "
                "49344, 1920, 1080, 30, 'h264', 1, '2026-09-05T00:00:00+00:00')", (str(vid),),
            )
        c.execute(
            "INSERT INTO catalog_segments VALUES (?, ?, 0, 49344, 'scene_detection', "
            "'2026-09-05T00:00:00+00:00')", (str(segment_id), str(video_id)),
        )
        c.execute("INSERT INTO catalog_segment_frames VALUES (?, 0, ?)",
                  (str(segment_id), frame.as_uri()))
        for start, status in ((0, "completed"), (4000, "failed")):
            c.execute(
                "INSERT INTO catalog_video_chunk_checkpoints VALUES "
                "(?, ?, ?, 'qwen-vl-video', 'qwen3-vl-embedding', 5000, 1000, ?, 1, NULL, "
                "'2026-09-05T00:00:00+00:00')", (str(video_id), start, start + 5000, status),
            )
        for start in (0, 8000):
            c.execute(
                "INSERT INTO catalog_video_chunk_embeddings VALUES "
                "(?, ?, ?, ?, 'qwen-vl-video', 'qwen3-vl-embedding', 2560, 5000, 1000, "
                "'not-json-must-never-be-read', '2026-09-05T00:00:00+00:00')",
                (str(uuid4()), str(video_id), start, start + 5000),
            )
    for revision in (1, 2):
        asr.save_asr_chunk(ASRChunkRecord(
            video_id=video_id, start_ms=0, end_ms=49344, provider="bailian-asr",
            model="qwen-audio-3.0-asr-flash", revision=revision, status="completed",
            attempt_count=1, sentences=[ASRSentence(start_ms=7840, end_ms=9960, text="领航北路与飞虎。")],
        ))
    catalog.save_annotation(SemanticAnnotation(
        segment_id=segment_id, origin=AnnotationOrigin.AI, provider="qwen",
        model="qwen3.8-flash", description="车辆驶入山林道路。",
        characters=["越野车"], actions=["行驶"], scene=["山林道路"],
        shot_type="全景",
    ))
    catalog.rebuild_semantic_spans(video_id)
    for index, raw in enumerate(("<p>越野NOA</p>", '```json\n[{"text":"专业级氮气减震"}]\n```', "```json\n[]\n```")):
        ocr.save_sample(OCRSampleRecord(
            video_id=video_id, start_ms=index * 5000, end_ms=(index + 1) * 5000,
            interval_ms=5000, provider="bailian-ocr", model="qwen3.5-ocr", revision=1,
            status="completed", attempt_count=1, text=raw,
        ))
    ocr.save_sample(OCRSampleRecord(
        video_id=other_id, start_ms=0, end_ms=5000, interval_ms=5000, provider="bailian-ocr",
        model="qwen3.5-ocr", revision=1, status="completed", attempt_count=1, text="other video",
    ))
    app = FastAPI()
    app.state.library_catalog = catalog
    app.state.library_asr_store = asr
    app.state.library_ocr_store = ocr
    app.include_router(router)
    return TestClient(app), db, video_id, other_id, catalog, frame


def test_visual_metadata_is_paginated_without_reading_vectors(indexed_video, monkeypatch):
    client, db, vid, _, catalog, _ = indexed_video
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    connect = catalog._connect

    def metadata_connection():
        c = connect()
        c.set_authorizer(lambda action, table, column, *_:
                         sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_READ
                         and column == "vector_json" else sqlite3.SQLITE_OK)
        return c

    monkeypatch.setattr(catalog, "_connect", metadata_connection)
    url = f"/api/v1/videos/{vid}/index-results/visual"
    first = client.get(url, params={"limit": 2}).json()
    assert first["has_more"] and len(first["items"]) == 2
    assert [(r["status"], r["dimensions"]) for r in first["items"]] == [
        ("completed", 2560), ("failed", None),
    ]
    second = client.get(url, params={"limit": 2, "offset": 2}).json()
    assert not second["has_more"] and len(second["items"]) == 1
    assert second["items"][0]["status"] == "untracked"
    assert not {"vector", "vector_json", "description"} & first["items"][0].keys()
    thumbnail = client.get(first["items"][0]["thumbnail_url"])
    assert thumbnail.status_code == 200 and thumbnail.headers["content-type"] == "image/png"
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before


def test_text_pages_preserve_sentences_revisions_and_raw_ocr(indexed_video):
    client, db, vid, other, _, _ = indexed_video
    before = db.read_bytes()
    base = f"/api/v1/videos/{vid}/index-results"
    first = client.get(f"{base}/asr", params={"limit": 1}).json()
    assert first["has_more"] and first["items"][0]["revision"] == 1
    second = client.get(f"{base}/asr", params={"limit": 1, "offset": 1}).json()
    assert not second["has_more"] and second["items"][0]["revision"] == 2
    assert second["items"][0]["sentences"][0] == {
        "start_ms": 7840, "end_ms": 9960, "text": "领航北路与飞虎。", "words": [],
    }
    ocr = client.get(f"{base}/ocr", params={"limit": 1, "offset": 1}).json()
    assert ocr["has_more"] and len(ocr["items"]) == 1
    assert ocr["items"][0]["readable_text"] == "专业级氮气减震"
    assert ocr["items"][0]["text"] == '```json\n[{"text":"专业级氮气减震"}]\n```'
    assert client.get(f"{base}/ocr", params={"offset": 99}).json()["items"] == []
    assert client.get(f"/api/v1/videos/{other}/index-results/asr").json()["items"] == []
    assert db.read_bytes() == before


def test_summary_page_exposes_compact_semantic_spans(indexed_video):
    client, _, vid, _, _, _ = indexed_video
    page = client.get(f"/api/v1/videos/{vid}/index-results/summary").json()
    assert page["source"] == "summary"
    assert page["items"] == [{
        "start_ms": 0,
        "end_ms": 49344,
        "summary": "车辆驶入山林道路。",
        "subjects": ["越野车"],
        "actions": ["行驶"],
        "scenes": ["山林道路"],
        "presentation_type": "全景",
        "pollution_level": "clean",
    }]


def test_index_boundaries_and_thumbnail_confinement(indexed_video):
    client, db, vid, other, _, frame = indexed_video
    base = f"/api/v1/videos/{vid}/index-results/ocr"
    for params in ({"limit": 0}, {"limit": 51}, {"offset": -1}):
        assert client.get(base, params=params).status_code == 422
    assert client.get(f"/api/v1/videos/{uuid4()}/index-results/ocr").status_code == 404
    assert client.get(f"/api/v1/videos/{vid}/index-results/bogus").status_code == 422
    assert client.get(f"/api/v1/videos/{other}/index-thumbnail?timestamp_ms=0").status_code == 404
    assert client.get(f"/api/v1/videos/{vid}/index-thumbnail?timestamp_ms=50000").status_code == 404
    outside = frame.parent.parent / "private.png"
    outside.write_bytes(frame.read_bytes())
    with sqlite3.connect(db) as c:
        c.execute("UPDATE catalog_segment_frames SET uri = ?", (outside.as_uri(),))
    assert client.get(f"/api/v1/videos/{vid}/index-thumbnail?timestamp_ms=0").status_code == 404
    page = client.get(f"/api/v1/videos/{vid}/index-results/visual").json()
    assert all(row["thumbnail_url"] is None for row in page["items"])


def test_source_media_supports_seeking_and_only_serves_registered_video(indexed_video, tmp_path):
    client, db, vid, _, _, _ = indexed_video
    media = tmp_path / 'movie.m4v'
    media.write_bytes(b'0123456789abcdef')
    with sqlite3.connect(db) as c:
        c.execute('UPDATE catalog_videos SET source_uri=? WHERE id=?', (media.as_uri(), str(vid)))
    response = client.get(f'/api/v1/videos/{vid}/source-media', headers={'Range': 'bytes=3-7'})
    assert response.status_code == 206
    assert response.content == b'34567'
    assert response.headers['content-range'] == 'bytes 3-7/16'
    assert response.headers['content-type'] == 'video/mp4'
    assert client.get(f'/api/v1/videos/{uuid4()}/source-media').status_code == 404
    secret = tmp_path / 'secret.txt'
    secret.write_text('private')
    with sqlite3.connect(db) as c:
        c.execute('UPDATE catalog_videos SET source_uri=? WHERE id=?', (secret.as_uri(), str(vid)))
    assert client.get(f'/api/v1/videos/{vid}/source-media').status_code == 404


@pytest.mark.parametrize(("raw", "readable"), [
    ("  hello   world  ", "hello world"),
    ("<p>道路 &amp; 山林</p>", "道路 & 山林"),
    ('```json\n[{"text":"前视","rotate_rect":[1,2]},{"text":"后视"}]\n```', "前视\n后视"),
    ('{"text":"文字"}', "文字"),
    ("```json\n[]\n```", ""),
    ("{broken json", "{broken json"),
])
def test_ocr_readable_presentation(raw, readable):
    assert readable_ocr_text(raw) == readable

"""Tests for local visual-family clustering and planner family exclusion."""

import json
import sqlite3
from uuid import uuid4

import pytest

from clipatlas.catalog.visual_family import (
    build_visual_families,
    ensure_family_table,
    load_families,
    ocr_signature,
    persist_families,
)
from clipatlas.roughcut.models import CandidateScore, RoughCutClip, RoughCutPlan
from clipatlas.roughcut.planner import RoughCutPlanner


def _conn() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        "CREATE TABLE catalog_segments (id TEXT PRIMARY KEY, video_id TEXT, start_ms INTEGER, end_ms INTEGER, source TEXT, created_at TEXT)"
    )
    connection.execute(
        "CREATE TABLE catalog_video_chunk_embeddings (id TEXT, video_id TEXT, start_ms INTEGER, end_ms INTEGER, provider TEXT, model TEXT, dimensions INTEGER, chunk_duration_ms INTEGER, overlap_ms INTEGER, vector_json TEXT, created_at TEXT)"
    )
    connection.execute(
        "CREATE TABLE catalog_ocr_samples (video_id TEXT, start_ms INTEGER, end_ms INTEGER, interval_ms INTEGER, provider TEXT, model TEXT, revision INTEGER, status TEXT, attempt_count INTEGER, last_error TEXT, text TEXT, updated_at TEXT)"
    )
    return connection


def _add_segment(connection, video_id, start_ms, end_ms) -> str:
    segment_id = str(uuid4())
    connection.execute(
        "INSERT INTO catalog_segments (id, video_id, start_ms, end_ms, source, created_at) VALUES (?,?,?,?,?,?)",
        (segment_id, video_id, start_ms, end_ms, "test", "2026-01-01T00:00:00+00:00"),
    )
    return segment_id


def _add_ocr(connection, video_id, start_ms, end_ms, text) -> None:
    connection.execute(
        "INSERT INTO catalog_ocr_samples (video_id, start_ms, end_ms, interval_ms, provider, model, revision, status, attempt_count, last_error, text, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (video_id, start_ms, end_ms, end_ms - start_ms, "p", "m", 1, "completed", 1, None, text, "2026-01-01T00:00:00+00:00"),
    )


def _add_chunk(connection, video_id, start_ms, end_ms, vector) -> None:
    connection.execute(
        "INSERT INTO catalog_video_chunk_embeddings (id, video_id, start_ms, end_ms, provider, model, dimensions, chunk_duration_ms, overlap_ms, vector_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (str(uuid4()), video_id, start_ms, end_ms, "p", "m", len(vector), end_ms - start_ms, 0, json.dumps(vector), "2026-01-01T00:00:00+00:00"),
    )


def test_ocr_same_screen_forms_family_across_videos() -> None:
    connection = _conn()
    s1 = _add_segment(connection, "v1", 0, 5000)
    s2 = _add_segment(connection, "v2", 0, 5000)
    _add_ocr(connection, "v1", 0, 5000, "21.4英寸后排吸顶大屏 七屏联动")
    _add_ocr(connection, "v2", 0, 5000, "21.4英寸后排吸顶大屏 七屏联动")
    families = build_visual_families(connection)
    assert families[s1] == families[s2]
    assert len({families[s1], families[s2]}) == 1


def test_different_ocr_stays_in_different_families() -> None:
    connection = _conn()
    s1 = _add_segment(connection, "v1", 0, 5000)
    s2 = _add_segment(connection, "v2", 0, 5000)
    _add_ocr(connection, "v1", 0, 5000, "医疗级双模制氧系统 7L每分")
    _add_ocr(connection, "v2", 0, 5000, "华为乾崑智驾 ADS5 全域")
    families = build_visual_families(connection)
    assert families[s1] != families[s2]


def test_same_video_near_segments_are_exempt() -> None:
    connection = _conn()
    s1 = _add_segment(connection, "v1", 0, 5000)
    s2 = _add_segment(connection, "v1", 5000, 10000)
    _add_ocr(connection, "v1", 0, 5000, "发布会大屏 泰钽700 上市")
    _add_ocr(connection, "v1", 5000, 10000, "发布会大屏 泰钽700 上市")
    families = build_visual_families(connection)
    # Continuous same-video footage must NOT be treated as a duplicate family.
    assert families[s1] != families[s2]


def test_embedding_similarity_forms_family() -> None:
    connection = _conn()
    s1 = _add_segment(connection, "v1", 0, 5000)
    s2 = _add_segment(connection, "v2", 10000, 15000)
    base = [0.01 * i for i in range(64)]
    _add_chunk(connection, "v1", 0, 5000, [x + 0.0001 for x in base])
    _add_chunk(connection, "v2", 10000, 15000, [x - 0.0001 for x in base])
    families = build_visual_families(connection, use_embeddings=True)
    assert families[s1] == families[s2]


def test_embeddings_off_by_default() -> None:
    connection = _conn()
    s1 = _add_segment(connection, "v1", 0, 5000)
    s2 = _add_segment(connection, "v2", 10000, 15000)
    base = [0.01 * i for i in range(64)]
    _add_chunk(connection, "v1", 0, 5000, [x + 0.0001 for x in base])
    _add_chunk(connection, "v2", 10000, 15000, [x - 0.0001 for x in base])
    families = build_visual_families(connection)
    assert families[s1] != families[s2]


def test_persist_and_load_roundtrip() -> None:
    connection = _conn()
    s1 = _add_segment(connection, "v1", 0, 5000)
    s2 = _add_segment(connection, "v2", 0, 5000)
    _add_ocr(connection, "v1", 0, 5000, "同一画面 完全一样 的字幕")
    _add_ocr(connection, "v2", 0, 5000, "同一画面 完全一样 的字幕")
    families = build_visual_families(connection)
    ensure_family_table(connection)
    inserted = persist_families(connection, families)
    assert inserted == 2
    loaded = load_families(connection)
    assert loaded == families


def test_ocr_signature_strips_json_noise() -> None:
    raw = '```json\n[{"rotate_rect": [1,2], "text": "泰钽700"}]```'
    sig = ocr_signature(raw)
    assert "泰钽" in sig
    assert "rotate_rect" not in sig


def _clip(segment_id, video_id, source_in_ms, timeline_in_ms) -> RoughCutClip:
    return RoughCutClip(
        beat_id=uuid4(),
        segment_id=segment_id,
        video_id=video_id,
        source_uri="file:///C:/v.mp4",
        source_in_ms=source_in_ms,
        source_out_ms=source_in_ms + 5000,
        timeline_in_ms=timeline_in_ms,
        timeline_out_ms=timeline_in_ms + 5000,
        score=0.9,
        score_breakdown=CandidateScore(
            segment_id=segment_id,
            semantic_score=0.9,
            action_score=0.9,
            scene_score=0.9,
            emotion_score=0.9,
            duration_fit_score=0.9,
            quality_score=0.9,
            continuity_bonus=0.0,
            reuse_penalty=0.0,
            total_score=0.9,
        ),
        selection_reason="test",
    )


class _Hit:
    def __init__(self, segment_id, video_id, source_start_ms, source_end_ms):
        self.segment_id = segment_id
        self.video_id = video_id
        self.source_start_ms = source_start_ms
        self.source_end_ms = source_end_ms
        self.schedule_level = "exact"


def test_family_conflict_excludes_used_family() -> None:
    fam_a = str(uuid4())
    fam_b = str(uuid4())
    fam_c = str(uuid4())
    families = {fam_a: "vf_0001", fam_b: "vf_0001", fam_c: "vf_0002"}
    planner = RoughCutPlanner(
        narration_store=None,  # type: ignore[arg-type]
        search=None,  # type: ignore[arg-type]
        store=None,  # type: ignore[arg-type]
        family_lookup=lambda sid: families.get(str(sid)),
    )
    prior = [_clip(fam_a, str(uuid4()), 0, 0)]
    used = planner._used_families(prior)
    assert used == {"vf_0001"}
    # Same family, different video: conflict.
    assert planner._family_conflict(_Hit(fam_b, str(uuid4()), 0, 5000), prior, used)
    # Different family: no conflict.
    assert not planner._family_conflict(_Hit(fam_c, str(uuid4()), 0, 5000), prior, used)
    # Same video, temporally near: continuous footage, exempt.
    assert not planner._family_conflict(_Hit(fam_b, prior[0].video_id, 3000, 8000), prior, used)

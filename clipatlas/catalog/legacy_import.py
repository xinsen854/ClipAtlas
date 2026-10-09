"""Import legacy fact-store annotations into the current catalog schema."""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from clipatlas.catalog.store import CatalogStore


@dataclass(slots=True)
class LegacyImportReport:
    matched_videos: int = 0
    imported_videos: int = 0
    retained_videos: int = 0
    imported_segments: int = 0
    imported_annotations: int = 0
    retained_annotations: int = 0
    imported_media_types: int = 0
    retained_media_types: int = 0
    imported_contamination_ranges: int = 0
    imported_asr_chunks: int = 0
    imported_ocr_samples: int = 0
    imported_video_embeddings: int = 0
    unmatched_videos: int = 0


def _connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    else:
        connection = sqlite3.connect(path.resolve())
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _json_strings(value: str) -> list[str]:
    try:
        decoded: Any = json.loads(value)
    except ValueError:
        decoded = value
    result: list[str] = []

    def visit(item: Any) -> None:
        if isinstance(item, str):
            text = item.strip()
            if text and text not in result:
                result.append(text[:240])
        elif isinstance(item, list):
            for child in item:
                visit(child)
        elif isinstance(item, dict):
            for child in item.values():
                visit(child)

    visit(decoded)
    return result


def _values_for_kinds(facts: list[sqlite3.Row], prefixes: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    for fact in facts:
        kind = str(fact["kind"]).casefold()
        if not any(kind == prefix or kind.startswith(prefix + ".") for prefix in prefixes):
            continue
        for value in _json_strings(fact["value_json"]):
            if value not in values:
                values.append(value)
    return values[:24]


def _annotation_payload(facts: list[sqlite3.Row], old_segment_id: str) -> dict[str, Any]:
    semantics = _values_for_kinds(facts, ("semantics", "scene_description", "video_content"))
    subjects = _values_for_kinds(facts, ("subjects", "subject", "person", "human"))
    actions = _values_for_kinds(facts, ("actions", "action", "interaction", "movement"))
    scenes = _values_for_kinds(facts, ("scenes", "scene", "environment", "setting"))
    objects = _values_for_kinds(
        facts, ("objects_relations", "object", "vehicle", "physical_object")
    )
    ocr = _values_for_kinds(
        facts, ("ocr", "ocr_text", "screen_text", "text_content", "text_overlay")
    )
    emotions = _values_for_kinds(facts, ("emotion_tone", "emotion", "mood", "atmosphere"))
    presentation = _values_for_kinds(facts, ("presentation_type",))
    description = "；".join(semantics[:3]) or "旧版中文事实迁移，待增补画面描述"
    confidence_values = [float(row["confidence"]) for row in facts if row["confidence"] is not None]
    return {
        "description": description,
        "characters": subjects[:12],
        "actions": actions[:12],
        "scene": scenes[:12],
        "emotions": emotions[:8],
        "objects": objects[:16],
        "ocr": ocr[:16],
        "shot_type": presentation[0] if presentation else None,
        "camera_motion": None,
        "confidence": max(confidence_values, default=0.6),
        "raw_payload": {
            "legacy_import": True,
            "legacy_segment_id": old_segment_id,
            "fact_count": len(facts),
        },
    }


def _media_type(
    facts: list[sqlite3.Row], contamination: list[str],
) -> tuple[str, float, int, int, str]:
    presentation = _values_for_kinds(facts, ("presentation_type",))
    kind = presentation[0].casefold() if presentation else "unknown"
    pollution = " ".join(contamination).casefold()
    has_black = "black" in pollution or "黑" in pollution
    has_text = any(token in pollution for token in ("text", "subtitle", "copyright"))
    if kind == "branding_bumper" or has_black:
        medium, ratio, blocks, subject = "title_card", 0.5, 2, 0
    elif kind == "technical_diagram":
        medium, ratio, blocks, subject = "technical_chart", 0.35, 3, 0
    elif kind == "cg_render":
        medium, ratio, blocks, subject = "cg", 0.15, 1, 1
    elif kind == "stage_screen":
        medium, ratio, blocks, subject = "scene", 0.35, 3, 1
    else:
        medium, ratio, blocks, subject = "scene", 0.35 if has_text else 0.05, 4 if has_text else 1, 1
    basis = f"legacy-facts:{kind};contamination={','.join(contamination[:8]) or 'none'}"
    return medium, ratio, blocks, subject, basis


def _target_segment(
    old_segment: sqlite3.Row, target_segments: list[sqlite3.Row],
) -> sqlite3.Row | None:
    exact = next((row for row in target_segments if row["start_ms"] == old_segment["start_ms"]
                  and row["end_ms"] == old_segment["end_ms"]), None)
    if exact is not None:
        return exact
    overlaps = [
        (min(row["end_ms"], old_segment["end_ms"])
         - max(row["start_ms"], old_segment["start_ms"]), row)
        for row in target_segments
    ]
    overlap, row = max(overlaps, default=(0, None), key=lambda item: item[0])
    return row if overlap > 0 else None


def import_legacy_annotations(source_db: Path, target_db: Path) -> LegacyImportReport:
    """Merge legacy facts by filename+size and time range without overwriting current data."""
    source_db, target_db = source_db.resolve(), target_db.resolve()
    if source_db == target_db:
        raise ValueError("source and target database must differ")
    CatalogStore(target_db)  # Apply current additive schema migrations first.
    report = LegacyImportReport()
    with _connect(source_db, readonly=True) as source, _connect(target_db) as target:
        if not all(_table_exists(source, name) for name in (
            "catalog_facts", "catalog_fact_observations", "library_items",
        )):
            raise ValueError("source database is not a supported legacy fact store")

        target_items: dict[tuple[str, int], sqlite3.Row] = {}
        for row in target.execute("SELECT * FROM library_items"):
            target_items[(Path(row["source_path"]).name.casefold(), row["size_bytes"])] = row

        facts_by_segment: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for row in source.execute(
            "SELECT * FROM catalog_facts WHERE superseded_by IS NULL ORDER BY created_at"
        ):
            if row["segment_id"]:
                facts_by_segment[row["segment_id"]].append(row)
        contamination_by_segment: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for row in source.execute("SELECT * FROM catalog_contamination_ranges"):
            if row["segment_id"]:
                contamination_by_segment[row["segment_id"]].append(row)

        for old_item in source.execute("SELECT * FROM library_items ORDER BY created_at"):
            key = (Path(old_item["source_path"]).name.casefold(), old_item["size_bytes"])
            target_item = target_items.get(key)
            if target_item is None:
                report.unmatched_videos += 1
                continue
            report.matched_videos += 1
            old_video = source.execute(
                "SELECT * FROM catalog_videos WHERE id=?", (old_item["video_id"],)
            ).fetchone()
            if old_video is None:
                report.unmatched_videos += 1
                continue
            checkpoint = target.execute(
                "SELECT video_id FROM catalog_preparation_checkpoints "
                "WHERE library_item_id=? AND fingerprint=?",
                (target_item["id"], target_item["fingerprint"]),
            ).fetchone()
            target_video_id = target_item["video_id"] or (checkpoint["video_id"] if checkpoint else None)
            target_video = target.execute(
                "SELECT * FROM catalog_videos WHERE id=?", (target_video_id,)
            ).fetchone() if target_video_id else None
            root = target.execute(
                "SELECT project_id FROM library_roots WHERE id=?", (target_item["root_id"],)
            ).fetchone()
            project_id = root["project_id"] if root else None

            if target_video is None:
                target_video_id = old_video["id"]
                target.execute(
                    """
                    INSERT OR IGNORE INTO catalog_videos(
                        id,filename,source_uri,duration_ms,width,height,fps,video_codec,
                        has_audio,project_id,fallback_role,created_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (target_video_id, old_video["filename"], Path(target_item["source_path"]).as_uri(),
                     old_video["duration_ms"], old_video["width"], old_video["height"],
                     old_video["fps"], old_video["video_codec"], old_video["has_audio"],
                     project_id, "normal", old_video["created_at"]),
                )
                for segment in source.execute(
                    "SELECT * FROM catalog_segments WHERE video_id=? ORDER BY start_ms",
                    (old_video["id"],),
                ):
                    target.execute(
                        "INSERT OR IGNORE INTO catalog_segments VALUES(?,?,?,?,?,?)",
                        tuple(segment),
                    )
                    report.imported_segments += 1
                report.imported_videos += 1
            else:
                report.retained_videos += 1

            target_segments = target.execute(
                "SELECT * FROM catalog_segments WHERE video_id=? ORDER BY start_ms",
                (target_video_id,),
            ).fetchall()
            old_segments = source.execute(
                "SELECT * FROM catalog_segments WHERE video_id=? ORDER BY start_ms",
                (old_video["id"],),
            ).fetchall()
            segment_map: dict[str, sqlite3.Row] = {}
            for old_segment in old_segments:
                mapped = _target_segment(old_segment, target_segments)
                if mapped is not None:
                    segment_map[old_segment["id"]] = mapped
                    exists = target.execute(
                        "SELECT 1 FROM catalog_annotations WHERE segment_id=? LIMIT 1",
                        (mapped["id"],),
                    ).fetchone()
                    if exists:
                        report.retained_annotations += 1
                    else:
                        payload = _annotation_payload(facts_by_segment[old_segment["id"]], old_segment["id"])
                        annotation_id = str(uuid5(
                            NAMESPACE_URL, f"clipatlas:legacy-annotation:{mapped['id']}"
                        ))
                        target.execute(
                            """
                            INSERT INTO catalog_annotations(
                                id,segment_id,origin,provider,model,description,characters_json,
                                actions_json,scene_json,emotions_json,objects_json,ocr_json,
                                shot_type,camera_motion,facts_json,confidence,verified,locked,
                                revision,raw_payload_json,created_at
                            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                            """,
                            (annotation_id, mapped["id"], "ai", "legacy-import", "qwen3.8-flash",
                             payload["description"], json.dumps(payload["characters"], ensure_ascii=False),
                             json.dumps(payload["actions"], ensure_ascii=False),
                             json.dumps(payload["scene"], ensure_ascii=False),
                             json.dumps(payload["emotions"], ensure_ascii=False),
                             json.dumps(payload["objects"], ensure_ascii=False),
                             json.dumps(payload["ocr"], ensure_ascii=False), payload["shot_type"],
                             payload["camera_motion"], "[]", payload["confidence"], 0, 0, 1,
                             json.dumps(payload["raw_payload"], ensure_ascii=False),
                             datetime.now(UTC).isoformat()),
                        )
                        report.imported_annotations += 1

                    contamination_rows = contamination_by_segment[old_segment["id"]]
                    contamination = [str(row["kind"]) for row in contamination_rows]
                    for contaminated in contamination_rows:
                        contamination_id = str(uuid5(
                            NAMESPACE_URL,
                            f"clipatlas:legacy-contamination:{mapped['id']}:{contaminated['id']}",
                        ))
                        target.execute(
                            """
                            INSERT OR IGNORE INTO catalog_contamination_ranges(
                                id,video_id,segment_id,start_ms,end_ms,kind,source,created_at
                            ) VALUES(?,?,?,?,?,?,?,?)
                            """,
                            (contamination_id, target_video_id, mapped["id"],
                             contaminated["start_ms"], contaminated["end_ms"],
                             contaminated["kind"], "legacy-facts", contaminated["created_at"]),
                        )
                        report.imported_contamination_ranges += 1
                    media_exists = target.execute(
                        "SELECT 1 FROM catalog_segment_media_types WHERE segment_id=?",
                        (mapped["id"],),
                    ).fetchone()
                    if media_exists:
                        report.retained_media_types += 1
                    else:
                        medium, ratio, blocks, subject, basis = _media_type(
                            facts_by_segment[old_segment["id"]], contamination,
                        )
                        target.execute(
                            """
                            INSERT INTO catalog_segment_media_types(
                                segment_id,subject_medium,text_ratio,text_block_count,
                                has_real_subject,basis,created_at
                            ) VALUES(?,?,?,?,?,?,?)
                            """,
                            (mapped["id"], medium, ratio, blocks, subject, basis,
                             datetime.now(UTC).isoformat()),
                        )
                        report.imported_media_types += 1

            for table, counter in (
                ("catalog_asr_chunks", "imported_asr_chunks"),
                ("catalog_ocr_samples", "imported_ocr_samples"),
                ("catalog_video_chunk_embeddings", "imported_video_embeddings"),
            ):
                columns = [row["name"] for row in source.execute(f"PRAGMA table_info({table})")]
                rows = source.execute(
                    f"SELECT * FROM {table} WHERE video_id=?", (old_video["id"],)
                ).fetchall()
                placeholders = ",".join("?" for _ in columns)
                for row in rows:
                    values = [target_video_id if column == "video_id" else row[column] for column in columns]
                    if "id" in columns:
                        column_id = columns.index("id")
                        values[column_id] = str(uuid5(
                            NAMESPACE_URL, f"clipatlas:legacy:{table}:{target_video_id}:{row['id']}"
                        ))
                    cursor = target.execute(
                        f"INSERT OR IGNORE INTO {table}({','.join(columns)}) VALUES({placeholders})",
                        values,
                    )
                    if cursor.rowcount:
                        setattr(report, counter, getattr(report, counter) + 1)

            target.execute(
                """
                INSERT INTO catalog_preparation_checkpoints(
                    library_item_id,fingerprint,video_id,updated_at
                ) VALUES(?,?,?,?)
                ON CONFLICT(library_item_id,fingerprint) DO UPDATE SET
                    video_id=excluded.video_id,updated_at=excluded.updated_at
                """,
                (target_item["id"], target_item["fingerprint"], target_video_id,
                 datetime.now(UTC).isoformat()),
            )
            target.execute(
                """
                UPDATE library_items SET status='COMPLETED',video_id=?,
                    processed_fingerprint=fingerprint,last_error=NULL,updated_at=?
                WHERE id=?
                """,
                (target_video_id, datetime.now(UTC).isoformat(), target_item["id"]),
            )
        target.commit()
    return report

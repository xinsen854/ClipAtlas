"""Read-only bilingual candidate-recall audit against an installed catalog."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clipatlas.retrieval.local_rough_cut import split_keywords
from clipatlas.retrieval.text_normalization import compact_text, matched_terms, strong_match

CURRENT_BATCH_ID = "3f006d3a-2ac7-4394-a5cc-05aaae60e9b1"
CURRENT_PROJECT_ID = "33f11f8c-d29c-4791-9bf7-7bd6c1fd85db"
OTHER_PROJECT_ID = "f493d5f6-3e82-4115-96d6-5d31592824aa"
_SENTENCE_SPLIT = re.compile(r"[。！？!?；;\n]+")


@dataclass(frozen=True)
class AnnotationRow:
    segment_id: str
    filename: str
    description: str
    text: str


def _connect_read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _annotation_rows(catalog_path: Path, project_id: str) -> list[AnnotationRow]:
    with _connect_read_only(catalog_path) as connection:
        rows = connection.execute(
            """
            WITH effective AS (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY segment_id
                    ORDER BY CASE WHEN origin = 'human' THEN 0 ELSE 1 END,
                             revision DESC, created_at DESC, rowid DESC
                ) AS rn
                FROM catalog_annotations
            )
            SELECT a.*, v.filename, m.subject_medium
            FROM effective a
            JOIN catalog_segments s ON s.id = a.segment_id
            JOIN catalog_videos v ON v.id = s.video_id
            LEFT JOIN catalog_segment_media_types m ON m.segment_id = s.id
            WHERE a.rn = 1 AND v.project_id = ? AND (s.end_ms - s.start_ms) >= 1500
              AND COALESCE(m.subject_medium, 'unknown') NOT IN (
                  'title_card', 'screen_capture', 'technical_chart'
              )
            """,
            (project_id,),
        ).fetchall()
    results: list[AnnotationRow] = []
    for row in rows:
        values = [str(row["description"] or "")]
        for column in (
            "characters_json",
            "actions_json",
            "scene_json",
            "emotions_json",
            "objects_json",
            "ocr_json",
        ):
            values.extend(str(value) for value in json.loads(row[column] or "[]"))
        for fact in json.loads(row["facts_json"] or "[]"):
            values.append(str(fact.get("value") or ""))
            statement = fact.get("statement") or {}
            proposition = statement.get("proposition") or {}
            values.extend(str(proposition.get(key) or "") for key in ("subject", "value", "scope"))
        results.append(
            AnnotationRow(
                segment_id=str(row["segment_id"]),
                filename=str(row["filename"]),
                description=str(row["description"] or ""),
                text=" ".join(value for value in values if value),
            )
        )
    return results


def _load_batch(narration_path: Path, batch_id: str) -> dict[str, Any]:
    with _connect_read_only(narration_path) as connection:
        row = connection.execute(
            "SELECT payload_json FROM narration_batches WHERE id = ?", (batch_id,)
        ).fetchone()
    if row is None:
        raise RuntimeError(f"batch not found: {batch_id}")
    return json.loads(row["payload_json"])


def _latest_unique_project_entries(narration_path: Path, project_id: str) -> list[dict[str, Any]]:
    with _connect_read_only(narration_path) as connection:
        rows = connection.execute(
            "SELECT payload_json FROM narration_batches WHERE project_id = ? ORDER BY created_at DESC",
            (project_id,),
        ).fetchall()
    entries: dict[str, dict[str, Any]] = {}
    for row in rows:
        for entry in json.loads(row["payload_json"]).get("entries", []):
            entries.setdefault(str(entry.get("code") or entry.get("id")), entry)
    return [entries[key] for key in sorted(entries)]


def _sentences(entry: dict[str, Any]) -> list[str]:
    return [
        sentence.strip(" *#|\t")
        for sentence in _SENTENCE_SPLIT.split(str(entry.get("text") or ""))
        if len(sentence.strip(" *#|\t")) >= 4
    ]


def _literal_matches(text: str, terms: list[str]) -> list[str]:
    compact = compact_text(text)
    return [term for term in terms if compact_text(term) in compact]


def audit_entries(entries: list[dict[str, Any]], rows: list[AnnotationRow]) -> dict[str, Any]:
    per_entry: list[dict[str, Any]] = []
    rescued_examples: list[dict[str, Any]] = []
    totals = {
        "sentences": 0,
        "searchable_sentences": 0,
        "monolingual_candidate_covered": 0,
        "bilingual_candidate_covered": 0,
        "monolingual_strong_covered": 0,
        "bilingual_strong_covered": 0,
        "bilingual_rescued": 0,
    }
    for entry in entries:
        metrics = {key: 0 for key in totals}
        for sentence in _sentences(entry):
            metrics["sentences"] += 1
            terms = split_keywords(sentence, include_ngram=False)
            if not terms:
                continue
            metrics["searchable_sentences"] += 1
            mono_hits: list[tuple[AnnotationRow, list[str]]] = []
            bilingual_hits: list[tuple[AnnotationRow, list[str]]] = []
            for row in rows:
                literal = _literal_matches(row.text, terms)
                bilingual = matched_terms(row.text, terms)
                if literal:
                    mono_hits.append((row, literal))
                if bilingual:
                    bilingual_hits.append((row, bilingual))
            mono_candidate = bool(mono_hits)
            bilingual_candidate = bool(bilingual_hits)
            mono_strong = any(strong_match(matches, terms) for _, matches in mono_hits)
            bilingual_strong = any(strong_match(matches, terms) for _, matches in bilingual_hits)
            metrics["monolingual_candidate_covered"] += int(mono_candidate)
            metrics["bilingual_candidate_covered"] += int(bilingual_candidate)
            metrics["monolingual_strong_covered"] += int(mono_strong)
            metrics["bilingual_strong_covered"] += int(bilingual_strong)
            if bilingual_candidate and not mono_candidate:
                metrics["bilingual_rescued"] += 1
                if len(rescued_examples) < 20:
                    row, matches = bilingual_hits[0]
                    rescued_examples.append(
                        {
                            "code": entry.get("code"),
                            "sentence": sentence,
                            "query_terms": terms,
                            "matched_concepts": matches,
                            "filename": row.filename,
                            "description": row.description,
                        }
                    )
        for key, value in metrics.items():
            totals[key] += value
        searchable = metrics["searchable_sentences"]
        metrics["candidate_coverage"] = (
            metrics["bilingual_candidate_covered"] / searchable if searchable else None
        )
        metrics["strong_coverage"] = (
            metrics["bilingual_strong_covered"] / searchable if searchable else None
        )
        per_entry.append(
            {"code": entry.get("code"), "title": entry.get("title"), **metrics}
        )
    searchable = totals["searchable_sentences"]
    totals["monolingual_candidate_rate"] = (
        totals["monolingual_candidate_covered"] / searchable if searchable else None
    )
    totals["bilingual_candidate_rate"] = (
        totals["bilingual_candidate_covered"] / searchable if searchable else None
    )
    totals["monolingual_strong_rate"] = (
        totals["monolingual_strong_covered"] / searchable if searchable else None
    )
    totals["bilingual_strong_rate"] = (
        totals["bilingual_strong_covered"] / searchable if searchable else None
    )
    return {"totals": totals, "entries": per_entry, "rescued_examples": rescued_examples}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=Path("D:/ClipAtlas/data"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    narration_path = args.data_root / "narration" / "narration.sqlite3"
    catalog_path = args.data_root / "library" / "library.sqlite3"
    current_entries = _load_batch(narration_path, CURRENT_BATCH_ID)["entries"]
    other_entries = _latest_unique_project_entries(narration_path, OTHER_PROJECT_ID)
    report = {
        "method": (
            "Read-only annotation candidate audit excluding known title-card, screen-capture and "
            "technical-chart segments. Candidate coverage is not human visual accuracy; strong "
            "coverage requires query-specific local concepts but is not DIRECT evidence."
        ),
        "current_20": audit_entries(
            current_entries, _annotation_rows(catalog_path, CURRENT_PROJECT_ID)
        ),
        "project_200w_other_tasks": audit_entries(
            other_entries, _annotation_rows(catalog_path, OTHER_PROJECT_ID)
        ),
    }
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

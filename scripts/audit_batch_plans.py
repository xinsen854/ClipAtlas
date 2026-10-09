"""Re-plan saved batches on database snapshots without network or formal exports."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from clipatlas.catalog.store import CatalogStore
from clipatlas.director.analyzer import DirectorAnalyzer
from clipatlas.director.service import DirectorService
from clipatlas.director.store import DirectorCacheStore
from clipatlas.retrieval.local_rough_cut import LocalRoughCutSearch
from clipatlas.roughcut.planner import RoughCutPlanner
from clipatlas.roughcut.store import RoughCutStore
from clipatlas.rules.store import ProjectRuleStore
from clipatlas.speech.store import NarrationStore

DATA = Path("D:/ClipAtlas/data")
CURRENT_BATCH_ID = "3f006d3a-2ac7-4394-a5cc-05aaae60e9b1"
CURRENT_PROJECT_ID = UUID("33f11f8c-d29c-4791-9bf7-7bd6c1fd85db")
OTHER_PROJECT_ID = UUID("f493d5f6-3e82-4115-96d6-5d31592824aa")


class NoNetworkAnalyzer(DirectorAnalyzer):
    async def analyze(self, *args: object, **kwargs: object):
        raise RuntimeError("batch plan audit forbids network access")


def _snapshot(source: Path, target: Path) -> None:
    with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as read:
        with sqlite3.connect(target) as write:
            read.backup(write)


def _batch_entries(narration_db: Path, batch_id: str) -> list[dict[str, Any]]:
    with sqlite3.connect(narration_db) as connection:
        row = connection.execute(
            "SELECT payload_json FROM narration_batches WHERE id=?", (batch_id,)
        ).fetchone()
    if row is None:
        raise RuntimeError(f"batch not found: {batch_id}")
    return json.loads(row[0])["entries"]


def _latest_project_entries(narration_db: Path, project_id: UUID) -> list[dict[str, Any]]:
    with sqlite3.connect(narration_db) as connection:
        rows = connection.execute(
            "SELECT payload_json FROM narration_batches WHERE project_id=? ORDER BY created_at DESC",
            (str(project_id),),
        ).fetchall()
    entries: dict[str, dict[str, Any]] = {}
    for (payload,) in rows:
        for entry in json.loads(payload).get("entries", []):
            entries.setdefault(str(entry.get("code") or entry.get("id")), entry)
    return [entries[key] for key in sorted(entries)]


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [row for row in rows if row.get("quality")]
    qualities = [row["quality"] for row in successful]
    claims = Counter()
    schedules = Counter()
    for quality in qualities:
        claims.update(quality["claim_counts"])
        schedules.update(quality["schedule_counts"])
    return {
        "tasks": len(rows),
        "succeeded": len(successful),
        "failed": len(rows) - len(successful),
        "clips": sum(row.get("clips", 0) for row in successful),
        "claim_counts": dict(claims),
        "schedule_counts": dict(schedules),
        "mean_one_shot_beat_ratio": (
            sum(q["one_shot_beat_ratio"] for q in qualities) / len(qualities)
            if qualities else None
        ),
        "mean_auto_s_claim_direct_ratio": (
            sum(q["auto_s_claim_direct_ratio"] for q in qualities
                if q["auto_s_claim_direct_ratio"] is not None)
            / sum(q["auto_s_claim_direct_ratio"] is not None for q in qualities)
            if any(q["auto_s_claim_direct_ratio"] is not None for q in qualities) else None
        ),
        "mean_auto_effective_claim_ratio": (
            sum(q["auto_effective_claim_ratio"] for q in qualities
                if q["auto_effective_claim_ratio"] is not None)
            / sum(q["auto_effective_claim_ratio"] is not None for q in qualities)
            if any(q["auto_effective_claim_ratio"] is not None for q in qualities) else None
        ),
        "repeated_source_ms": sum(q["repeated_source_ms"] for q in qualities),
        "batch_repeated_source_ms": sum(q["batch_repeated_source_ms"] for q in qualities),
    }


async def _run_group(
    planner: RoughCutPlanner,
    project_id: UUID,
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    batch_usage: dict[str, list[tuple[int, int, int]]] = {}
    for index, entry in enumerate(entries):
        row: dict[str, Any] = {
            "code": entry.get("code"),
            "title": entry.get("title"),
            "track_id": entry.get("narration_track_id"),
        }
        try:
            plan = await planner.create_plan(
                project_id,
                narration_track_id=UUID(str(entry["narration_track_id"])),
                activate=False,
                batch_usage=batch_usage,
                batch_index=index,
            )
            for clip in plan.clips:
                batch_usage.setdefault(str(clip.video_id), []).append(
                    (clip.source_in_ms, clip.source_out_ms, index)
                )
            row.update(
                {
                    "plan_id": str(plan.id),
                    "beats": len(plan.beats),
                    "clips": len(plan.clips),
                    "warnings": plan.warnings,
                    "quality": plan.quality_report.model_dump(mode="json")
                    if plan.quality_report else None,
                }
            )
        except Exception as exc:  # noqa: BLE001 - audit records per-track failures
            row["error"] = f"{type(exc).__name__}: {exc}"
        rows.append(row)
        print(f"{project_id} {index + 1}/{len(entries)} {entry.get('code')}", flush=True)
    return rows


async def main() -> int:
    output = ROOT / "scratch_ref" / (
        "batch_plan_audit_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    output.mkdir(parents=True)
    for relative, name in (
        ("library/library.sqlite3", "library.sqlite3"),
        ("narration/narration.sqlite3", "narration.sqlite3"),
        ("director/director.sqlite3", "director.sqlite3"),
        ("projects/project_rules.sqlite3", "rules.sqlite3"),
    ):
        _snapshot(DATA / relative, output / name)

    narration = NarrationStore(output / "narration.sqlite3")
    catalog = CatalogStore(output / "library.sqlite3")
    rules = ProjectRuleStore(output / "rules.sqlite3")
    plans = RoughCutStore(output / "plans.sqlite3")
    analyzer = NoNetworkAnalyzer(
        api_key="offline", base_url="http://127.0.0.1:1", timeout_seconds=1
    )
    planner = RoughCutPlanner(
        narration_store=narration,
        search=LocalRoughCutSearch(search=None, catalog=catalog),
        store=plans,
        rule_store=rules,
        director=DirectorService(analyzer, DirectorCacheStore(output / "director.sqlite3")),
    )
    current_entries = _batch_entries(output / "narration.sqlite3", CURRENT_BATCH_ID)
    other_entries = _latest_project_entries(output / "narration.sqlite3", OTHER_PROJECT_ID)
    current = await _run_group(planner, CURRENT_PROJECT_ID, current_entries)
    other = await _run_group(planner, OTHER_PROJECT_ID, other_entries)
    report = {
        "method": (
            "Plans generated on SQLite snapshots with current source. Network calls are forbidden. "
            "A compatible old Director cache may be used only through the product's explicit fallback."
        ),
        "network_calls": 0,
        "current_20": {"summary": _aggregate(current), "tasks": current},
        "project_200w_other_tasks": {"summary": _aggregate(other), "tasks": other},
    }
    report_path = output / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("REPORT=" + str(report_path), flush=True)
    print(json.dumps({
        "current_20": report["current_20"]["summary"],
        "project_200w_other_tasks": report["project_200w_other_tasks"]["summary"],
    }, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

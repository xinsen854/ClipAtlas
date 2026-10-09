"""Run typed claim retrieval against a database snapshot; no provider calls."""

import asyncio
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from clipatlas.catalog.store import CatalogStore
from clipatlas.director.models import DirectorUnit
from clipatlas.retrieval.local_rough_cut import LocalRoughCutSearch
from scripts.audit_typed_claims_current_script import CLAIMS, PROJECT

OUT = ROOT / "scratch_ref" / "current_script_local_retrieval"


async def main() -> None:
    OUT.mkdir(exist_ok=True)
    snapshot = OUT / "library.sqlite3"
    source_path = Path("D:/ClipAtlas/data/library/library.sqlite3")
    with sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True) as source:
        with sqlite3.connect(snapshot) as target:
            source.backup(target)
    catalog = CatalogStore(snapshot)
    search = LocalRoughCutSearch(search=None, catalog=catalog)
    video_ids = catalog.list_video_ids_for_project(__import__("uuid").UUID(PROJECT))
    output = []
    for claim in CLAIMS:
        unit = DirectorUnit(
            text_range=claim.source_quote, importance="S", topic=claim.claim_id,
            claims=[claim], visual_goal="proof" if claim.goal == "proof" else "related",
        )
        hits = await search.search_with_context(
            claim.source_quote,
            context={
                "rough_cut": True, "needed_duration_ms": 4000, "minimum_shot_ms": 1000,
                "director_importance": "S",
                "retrieval_intent": {"director_units": [unit.model_dump(mode="json")]},
                "allow_tail_text": False,
            }, limit=12, video_ids=video_ids,
        )
        rows = [{
            "filename": hit.filename, "segment_id": str(hit.segment_id),
            "source_start_ms": hit.source_start_ms, "source_end_ms": hit.source_end_ms,
            "schedule_level": hit.schedule_level, "score": hit.score,
            "reason": hit.query_relevance_reason,
            "media": catalog.get_segment_media_type(hit.segment_id),
        } for hit in hits]
        output.append({"claim_id": claim.claim_id, "quote": claim.source_quote, "hits": rows})
        print(claim.claim_id, [(r["filename"], r["schedule_level"], round(r["score"], 2))
                               for r in rows[:3]])
    report = OUT / "report.json"
    report.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print("REPORT=" + str(report))


if __name__ == "__main__":
    asyncio.run(main())

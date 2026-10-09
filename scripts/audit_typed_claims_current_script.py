"""Read-only typed-claim audit for the current Beijing Off-road narration."""

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from clipatlas.catalog.store import CatalogStore
from clipatlas.director.claim_matching import match_claim, evidence_records
from clipatlas.domain.evidence import EvidenceAlternative, Proposition, VisualClaim

DB = Path("D:/ClipAtlas/data/library/library.sqlite3")
PROJECT = "33f11f8c-d29c-4791-9bf7-7bd6c1fd85db"
OUTPUT = ROOT / "scratch_ref" / "current_script_typed_claim_audit.json"


def p(subject, predicate, value, *, unit=None, scope=None):
    return Proposition(subject=subject, predicate=predicate, value=value, unit=unit, scope=scope)


def c(identifier, quote, conditions, kinds, *, goal="proof", same=True, simultaneous=False):
    return VisualClaim(claim_id=identifier, source_quote=quote, goal=goal, any_of=[
        EvidenceAlternative(all_of=conditions, allowed_kinds=kinds,
                            same_entity=same, simultaneous=simultaneous)
    ])


CLAIMS = [
    c("brand", "北京越野", [p("北京越野", "identity", "北京越野")], ["visual", "source_text"]),
    c("base", "实体基地", [p("连云港山海逐浪越野基地", "presence", "连云港山海逐浪越野基地")], ["source_text"]),
    c("history_68", "68年越野车制造史", [p("制造历史", "quantity", "68", unit="年", scope="制造历史")], ["source_text"]),
    c("first_vehicle", "中国第一代越野车", [p("中国第一代越野车", "presence", "中国第一代越野车")], ["visual", "source_text"]),
    c("million_users", "超百万用户", [p("用户数量", "quantity", "100", unit="万", scope="用户数量")], ["source_text"]),
    c("events_1500", "一年1500多场线下活动", [p("线下活动", "quantity", "1500", unit="场", scope="线下活动")], ["source_text"]),
    c("cities_270", "覆盖270城的服务网", [p("服务网络", "quantity", "270", unit="城", scope="服务网络")], ["source_text"]),
    c("titan700", "泰钽700", [p("泰钽700", "identity", "泰钽700")], ["visual", "source_text"]),
    c("ads", "华为乾崑智驾ADS 5.0 MAX", [p("泰钽700", "identity", "泰钽700"),
      p("泰钽700", "configuration", "ADS 5.0 MAX")], ["source_text"]),
    c("frame", "八横两纵高强钢大梁", [p("泰钽700", "identity", "泰钽700"),
      p("泰钽700", "configuration", "八横两纵高强钢大梁")], ["source_text", "diagram"]),
    c("city_drive", "城市里它是智驾代劳的通勤旗舰", [p("泰钽700", "identity", "泰钽700"),
      p("泰钽700", "action", "行驶"), p("场景", "scene", "城市道路")], ["visual"], simultaneous=True),
    c("offroad", "进了旷野", [p("泰钽700", "identity", "泰钽700"),
      p("泰钽700", "action", "行驶"), p("场景", "scene", "山路")], ["visual"], simultaneous=True),
    c("locks", "三把锁", [p("泰钽700", "identity", "泰钽700"),
      p("泰钽700", "configuration", "三把锁")], ["source_text", "diagram"]),
    c("bj40_range", "BJ40增程", [p("BJ40", "identity", "BJ40"),
      p("BJ40", "configuration", "增程")], ["source_text"]),
    c("flying_variant", "BJ40增程悦野飞行版", [p("BJ40增程悦野飞行版", "identity", "BJ40增程悦野飞行版")], ["visual", "source_text"]),
    c("vehicle_drone", "车载无人机", [p("BJ40增程悦野飞行版", "identity", "BJ40增程悦野飞行版"),
      p("BJ40增程悦野飞行版", "configuration", "车载无人机")], ["visual", "source_text"]),
    c("family_lifestyle", "普通家庭也能把两天山野过成每周日常",
      [p("场景", "scene", "露营")], ["visual"], goal="related", same=False),
]


def main():
    connection = sqlite3.connect(DB.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    rows = connection.execute("""WITH effective AS (
        SELECT *, ROW_NUMBER() OVER(PARTITION BY segment_id ORDER BY
        CASE WHEN origin='human' THEN 0 ELSE 1 END, revision DESC, created_at DESC, rowid DESC) rn
      FROM catalog_annotations)
      SELECT effective.*, s.start_ms AS segment_start_ms, s.end_ms AS segment_end_ms,
             v.filename, v.source_uri
      FROM effective JOIN catalog_segments s ON s.id=effective.segment_id
      JOIN catalog_videos v ON v.id=s.video_id
      WHERE effective.rn=1 AND v.project_id=?""", (PROJECT,)).fetchall()
    output = []
    for claim in CLAIMS:
        matches = []
        for row in rows:
            annotation = CatalogStore._annotation_from_row(row)
            result = match_claim(claim, "S", evidence_records(annotation))
            if result.level in {"DIRECT", "SUPPORT", "REJECT"}:
                matches.append({
                    "level": result.level, "filename": row["filename"],
                    "segment_id": row["segment_id"], "start_ms": row["segment_start_ms"],
                    "end_ms": row["segment_end_ms"], "result": result.model_dump(mode="json"),
                    "description": row["description"], "ocr": json.loads(row["ocr_json"]),
                })
        rank = {"DIRECT": 0, "SUPPORT": 1, "REJECT": 2}
        matches.sort(key=lambda item: (rank[item["level"]], -len(item["result"]["matched_conditions"]),
                                       item["filename"], item["start_ms"]))
        summary = {"claim_id": claim.claim_id, "quote": claim.source_quote,
                   "direct_candidates": sum(m["level"] == "DIRECT" for m in matches),
                   "support_candidates": sum(m["level"] == "SUPPORT" for m in matches),
                   "examples": matches[:5]}
        output.append(summary)
        print(f"{claim.claim_id}: DIRECT={summary['direct_candidates']} SUPPORT={summary['support_candidates']}")
        for item in summary["examples"][:2]:
            print(" ", item["level"], item["filename"], item["start_ms"], item["end_ms"])
    OUTPUT.write_text(json.dumps({"project_id": PROJECT, "claims": output},
                                 ensure_ascii=False, indent=2), encoding="utf-8")
    print("REPORT=" + str(OUTPUT))


if __name__ == "__main__":
    main()

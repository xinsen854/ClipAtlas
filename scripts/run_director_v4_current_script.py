"""Run one isolated Director v4 analysis for the current Beijing Off-road script."""

import asyncio
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from clipatlas.director.analyzer import DirectorAnalyzer
from clipatlas.rules.store import ProjectRuleStore
from clipatlas.settings.bailian import derive_bailian_endpoints
from clipatlas.settings.store import SettingsStore

DATA = Path("D:/ClipAtlas/data")
OUTPUT = ROOT / "scratch_ref" / "current_script_director_v4.json"
PROJECT_ID = "33f11f8c-d29c-4791-9bf7-7bd6c1fd85db"


def existing_script() -> str:
    connection = sqlite3.connect((DATA / "director/director.sqlite3").as_uri() + "?mode=ro", uri=True)
    for (raw,) in connection.execute("SELECT analysis_json FROM director_analyses ORDER BY created_at DESC"):
        payload = json.loads(raw)
        text = payload.get("script_text", "")
        if "从造一台好车，到创造一种越野生活" in text and "一年1500多场线下活动" in text:
            return text
    raise RuntimeError("matching saved narration was not found")


async def main() -> None:
    settings = SettingsStore(DATA / "config/settings.json")
    key = settings.resolve_secret("bailian_api_key")
    persisted = settings.read_persisted()
    base = persisted.bailian_base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    if not key:
        raise RuntimeError("Bailian API key is not configured")
    endpoints = derive_bailian_endpoints(base)
    script = existing_script()
    rule_store = ProjectRuleStore(DATA / "projects/project_rules.sqlite3")
    from uuid import UUID
    pack = rule_store.get_active(UUID(PROJECT_ID))
    rules_text = ProjectRuleStore._rules_json(pack.rules) if pack else ""
    analyzer = DirectorAnalyzer(api_key=key, base_url=endpoints.openai_compatible)
    analysis = await analyzer.analyze(script, rules_revision="isolated-v4-validation",
                                      rules_text=rules_text)
    OUTPUT.write_text(analysis.model_dump_json(indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(OUTPUT), "prompt_version": analysis.prompt_version,
        "units": len(analysis.units),
        "claims": sum(len(unit.claims) for unit in analysis.units),
        "issues": sum(len(unit.contract_issues) for unit in analysis.units),
        "invented_takeoff": [
            {"unit": unit.text_range, "claim": claim.source_quote}
            for unit in analysis.units for claim in unit.claims
            for alternative in claim.any_of for condition in alternative.all_of
            if condition.predicate == "action" and condition.value in {"起飞", "升空", "无人机起飞"}
        ],
    }, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())

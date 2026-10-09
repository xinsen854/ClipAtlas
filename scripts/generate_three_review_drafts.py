"""Generate three isolated review drafts from current source and saved local evidence."""

import asyncio
import json
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from clipatlas.catalog.store import CatalogStore
from clipatlas.director.analyzer import DirectorAnalyzer
from clipatlas.director.service import DirectorService
from clipatlas.director.store import DirectorCacheStore
from clipatlas.exports.jianying import PyJianYingDraftBackend
from clipatlas.exports.models import JianyingExportSettings
from clipatlas.exports.service import TimelineExportService
from clipatlas.retrieval.local_rough_cut import LocalRoughCutSearch
from clipatlas.roughcut.planner import RoughCutPlanner
from clipatlas.roughcut.store import RoughCutStore
from clipatlas.rules.store import ProjectRuleStore
from clipatlas.speech.store import NarrationStore

DATA = Path("D:/ClipAtlas/data")
DRAFT_ROOT = Path("D:/JianyingPro Drafts")
RUN = ROOT / "scratch_ref" / ("three_drafts_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
PROJECT = UUID("33f11f8c-d29c-4791-9bf7-7bd6c1fd85db")
TRACKS = [
    (UUID("8792ba88-2829-5f13-846d-1b505dbb06d0"), "越野生活与长期主义"),
    (UUID("73238729-cc48-5325-9054-2f9cc8af1b2e"), "泰钽700四位一体"),
    (UUID("9c312e29-1b7a-5e34-b4ac-c8a7ad9eeef3"), "BJ40悦野飞行版"),
]


class NoNetworkAnalyzer(DirectorAnalyzer):
    async def analyze(self, *args, **kwargs):
        raise RuntimeError("review generation requires an existing Director cache")


def snapshot(source: Path, target: Path) -> None:
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as read:
        with sqlite3.connect(target) as write:
            read.backup(write)


async def main() -> None:
    RUN.mkdir(parents=True)
    DRAFT_ROOT.mkdir(parents=True, exist_ok=True)
    for relative, target in [
        ("library/library.sqlite3", "library.sqlite3"),
        ("narration/narration.sqlite3", "narration.sqlite3"),
        ("director/director.sqlite3", "director.sqlite3"),
        ("projects/project_rules.sqlite3", "rules.sqlite3"),
    ]:
        snapshot(DATA / relative, RUN / target)

    narration = NarrationStore(RUN / "narration.sqlite3")
    catalog = CatalogStore(RUN / "library.sqlite3")
    plans = RoughCutStore(RUN / "plans.sqlite3")
    rules = ProjectRuleStore(RUN / "rules.sqlite3")
    locked_pack = rules.get_by_revision(PROJECT, 1)
    rules.get_active = lambda project_id: locked_pack
    analyzer = NoNetworkAnalyzer(
        api_key="offline", base_url="http://127.0.0.1:1",
        prompt_version="director-v3-evidence-hierarchy-zh",
    )
    director = DirectorService(analyzer, DirectorCacheStore(RUN / "director.sqlite3"))
    planner = RoughCutPlanner(
        narration_store=narration,
        search=LocalRoughCutSearch(search=None, catalog=catalog),
        store=plans,
        rule_store=rules,
        director=director,
    )
    export = TimelineExportService(
        rough_cut_store=plans, narration_store=narration,
        export_root=RUN / "otio", jianying_backend=PyJianYingDraftBackend(),
    )
    stamp = datetime.now().strftime("%m%d-%H%M")
    report = []
    batch_usage = {}
    for index, (track_id, label) in enumerate(TRACKS, 1):
        track = narration.get_track(track_id)
        if track is None:
            raise RuntimeError(f"missing narration track: {track_id}")
        plan = await planner.create_plan(
            PROJECT, narration_track_id=track_id, activate=False,
            batch_usage=batch_usage, batch_index=index - 1,
        )
        for clip in plan.clips:
            batch_usage.setdefault(str(clip.video_id), []).append(
                (clip.source_in_ms, clip.source_out_ms, index - 1)
            )
        name = f"ClipAtlas-新规则测试{index}-{label}-{stamp}"
        artifact = export.export_jianying(
            plan.id, draft_name=name,
            settings=JianyingExportSettings(
                draft_root=DRAFT_ROOT, width=1080, height=1920,
                cover_title=label,
            ),
        )
        export.export_otio(plan.id)
        levels = Counter(clip.schedule_level for clip in plan.clips)
        fits = Counter(str(clip.director_fit) for clip in plan.clips)
        row = {
            "index": index, "label": label, "track_id": str(track_id),
            "plan_id": str(plan.id), "draft_name": name,
            "draft_path": str(artifact.output_path),
            "duration_ms": plan.total_duration_ms,
            "beats": len(plan.beats), "clips": len(plan.clips),
            "videos": len({clip.video_id for clip in plan.clips}),
            "schedule_levels": dict(levels), "director_fits": dict(fits),
            "quality": plan.quality_report.model_dump(mode="json") if plan.quality_report else None,
            "warnings": plan.warnings,
        }
        report.append(row)
        print(json.dumps({k: row[k] for k in (
            "index", "label", "draft_path", "duration_ms", "beats", "clips",
            "videos", "schedule_levels", "director_fits"
        )}, ensure_ascii=False), flush=True)
    report_path = RUN / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("REPORT=" + str(report_path), flush=True)


if __name__ == "__main__":
    asyncio.run(main())

from itertools import pairwise
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from clipatlas.domain.models import AnnotationOrigin, SemanticAnnotation
from clipatlas.retrieval.search import SemanticSearchHit
from clipatlas.roughcut.planner import RoughCutPlanner
from clipatlas.roughcut.store import RoughCutStore
from clipatlas.speech.models import (
    NarrationSourceMode,
    NarrationTrack,
    NarrationUnit,
    TimingQuality,
)
from clipatlas.speech.store import NarrationStore


class DeterministicSegmentSearch:
    def project_video_ids(self, project_id: UUID) -> list[UUID]:
        return list({hit.video_id for hits in self._results.values() for hit in hits})

    def __init__(self, results: dict[str, list[SemanticSearchHit]]) -> None:
        self._results = results
        self.queries: list[str] = []

    async def search(
        self,
        query: str,
        limit: int = 10,
        video_ids: list[UUID] | None = None,
    ) -> list[SemanticSearchHit]:
        del video_ids
        self.queries.append(query)
        return list(self._results.get(query, []))[:limit]


def _hit(
    *,
    description: str,
    action: str,
    start_ms: int,
    end_ms: int,
) -> SemanticSearchHit:
    segment_id = uuid4()
    annotation = SemanticAnnotation(
        segment_id=segment_id,
        origin=AnnotationOrigin.HUMAN,
        description=description,
        actions=[action],
        confidence=0.95,
        verified=True,
    )
    return SemanticSearchHit(
        segment_id=segment_id,
        video_id=uuid4(),
        source_uri=f"file:///footage/{segment_id}.mp4",
        source_start_ms=start_ms,
        source_end_ms=end_ms,
        score=0.92,
        effective_description=description,
        annotation=annotation,
        embedding_provider="test",
        embedding_model="test-model",
        embedding_dimensions=3,
    )


@pytest.mark.asyncio
async def test_active_narration_drives_complete_rough_cut_timeline(tmp_path: Path) -> None:
    project_id = uuid4()
    narration_store = NarrationStore(tmp_path / "narration.sqlite3")
    track = NarrationTrack(
        project_id=project_id,
        source_mode=NarrationSourceMode.TTS,
        script_hash="integration-script",
        duration_ms=3500,
        timing_quality=TimingQuality.UNIT_EXACT,
        revision=1,
    )
    narration_store.save_track(track)

    unit_specs = [
        ("女人推开旧仓库门", 0, 1200),
        ("她看到桌上的红色文件夹", 1200, 2000),
        ("远处警灯照亮雨夜街道", 2000, 3500),
    ]
    for sequence, (text, start_ms, end_ms) in enumerate(unit_specs):
        narration_store.save_unit(
            NarrationUnit(
                track_id=track.id,
                sequence=sequence,
                text=text,
                text_hash=f"unit-{sequence}",
                start_ms=start_ms,
                end_ms=end_ms,
            )
        )
    assert narration_store.activate_track(project_id, track.id) is True

    results = {
        "女人推开旧仓库门": [
            _hit(
                description="女人进入旧仓库",
                action="推开仓库门",
                start_ms=5000,
                end_ms=9000,
            )
        ],
        "她看到桌上的红色文件夹": [
            _hit(
                description="桌上放着红色文件夹",
                action="看到红色文件夹",
                start_ms=12000,
                end_ms=15000,
            )
        ],
        "远处警灯照亮雨夜街道": [
            _hit(
                description="雨夜街道闪烁警灯",
                action="警灯照亮街道",
                start_ms=20000,
                end_ms=25000,
            )
        ],
    }
    search = DeterministicSegmentSearch(results)
    rough_cut_store = RoughCutStore(tmp_path / "roughcut.sqlite3")
    planner = RoughCutPlanner(
        narration_store=narration_store,
        search=search,
        store=rough_cut_store,
    )

    plan = await planner.create_plan(project_id)

    assert search.queries == [text for text, _, _ in unit_specs]
    assert plan.narration_track_id == track.id
    assert plan.total_duration_ms == track.duration_ms == 3500
    assert plan.clips[0].timeline_in_ms == 0
    assert plan.clips[-1].timeline_out_ms == 3500
    assert all(
        left.timeline_out_ms == right.timeline_in_ms
        for left, right in pairwise(plan.clips)
    )
    assert all(
        clip.source_out_ms - clip.source_in_ms
        == clip.timeline_out_ms - clip.timeline_in_ms
        for clip in plan.clips
    )
    assert rough_cut_store.get_active_plan(project_id) == plan
    assert rough_cut_store.get_plan(plan.id) == plan


@pytest.mark.asyncio
async def test_imported_track_only_uses_local_estimated_timing_without_aligner(
    tmp_path: Path,
) -> None:
    project_id = uuid4()
    narration_store = NarrationStore(tmp_path / "imported-narration.sqlite3")
    track = NarrationTrack(
        project_id=project_id,
        source_mode=NarrationSourceMode.IMPORTED,
        script_hash="imported-script",
        duration_ms=4200,
        timing_quality=TimingQuality.TRACK_ONLY,
        revision=1,
    )
    narration_store.save_track(track)

    texts = ["雨夜里女人推开仓库门。", "她发现桌上的红色文件夹。"]
    for sequence, text in enumerate(texts):
        narration_store.save_unit(
            NarrationUnit(
                track_id=track.id,
                sequence=sequence,
                text=text,
                text_hash=f"imported-{sequence}",
                start_ms=None,
                end_ms=None,
                source=NarrationSourceMode.IMPORTED,
            )
        )
    assert narration_store.activate_track(project_id, track.id) is True

    first_hit = _hit(
        description="女人在雨夜仓库中发现红色文件夹",
        action="推门并查看文件夹",
        start_ms=10_000,
        end_ms=16_000,
    )
    search = DeterministicSegmentSearch(
        {
            texts[0]: [first_hit], texts[1]: [first_hit],
        }
    )
    rough_cut_store = RoughCutStore(tmp_path / "imported-roughcut.sqlite3")
    planner = RoughCutPlanner(
        narration_store=narration_store,
        search=search,
        store=rough_cut_store,
    )

    plan = await planner.create_plan(project_id)
    assert search.queries == texts
    assert plan.clips[-1].timeline_out_ms == 4200
    assert any("本地文本权重估算" in warning for warning in plan.warnings)
    assert narration_store.get_track(track.id).timing_quality == TimingQuality.TRACK_ONLY

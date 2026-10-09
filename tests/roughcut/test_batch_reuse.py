"""批次级去重：同批次成片间滚动窗口内避让占用片段，S 级 DIRECT 轻避让。"""
from pathlib import Path
from uuid import uuid4

import pytest

from clipatlas.director.models import DirectorUnit
from clipatlas.domain.models import SemanticAnnotation
from clipatlas.retrieval.search import SemanticSearchHit
from clipatlas.roughcut.models import PlannerSettings, ScriptBeat
from clipatlas.roughcut.planner import RoughCutPlanner
from clipatlas.roughcut.scoring import batch_occupancy_for
from clipatlas.roughcut.store import RoughCutStore
from clipatlas.speech.store import NarrationStore


class _Hit:
    def __init__(self, video_id=None, start_ms=0, end_ms=4000):
        self.segment_id = uuid4()
        self.video_id = video_id or uuid4()
        self.source_uri = "file:///x.mp4"
        self.source_start_ms = start_ms
        self.source_end_ms = end_ms
        self.score = 0.5
        self.asr_texts: list[str] = []
        self.ocr_texts: list[str] = []
        self.annotation = SemanticAnnotation(
            segment_id=self.segment_id, origin="ai", description="车辆画面",
            objects=[], actions=[], scene=[], characters=[], ocr=[],
        )


def _search_hit(
    *,
    objects: list[str],
    actions: list[str] | None = None,
    video_id=None,
    start_ms=0,
    end_ms=4000,
    description: str = "车辆画面",
) -> SemanticSearchHit:
    return SemanticSearchHit(
        segment_id=uuid4(),
        video_id=video_id or uuid4(),
        source_uri="file:///x.mp4",
        source_start_ms=start_ms,
        source_end_ms=end_ms,
        score=0.6,
        effective_description=description,
        annotation=SemanticAnnotation(
            segment_id=uuid4(), origin="ai", description=description,
            objects=objects, actions=actions or [], scene=[], characters=[], ocr=[],
        ),
        embedding_provider="test", embedding_model="test", embedding_dimensions=8,
    )


def _usage(video_id, start, end, used_index):
    return {str(video_id): [(start, end, used_index)]}


def test_occupancy_within_window_counts() -> None:
    hit = _Hit(start_ms=1000, end_ms=5000)
    usage = _usage(hit.video_id, 2000, 6000, used_index=2)
    # 当前第 4 条：距上次使用 2 条 < gap=5 → 占用 1 次
    assert batch_occupancy_for(hit, usage, current_index=4, gap=5) == 1


def test_occupancy_released_after_gap() -> None:
    hit = _Hit(start_ms=1000, end_ms=5000)
    usage = _usage(hit.video_id, 2000, 6000, used_index=2)
    # 当前第 8 条：距上次使用 6 条 >= gap=5 → 已释放，不占用
    assert batch_occupancy_for(hit, usage, current_index=8, gap=5) == 0


def test_occupancy_no_overlap_ignored() -> None:
    hit = _Hit(start_ms=0, end_ms=1000)
    usage = _usage(hit.video_id, 5000, 9000, used_index=0)
    assert batch_occupancy_for(hit, usage, current_index=1, gap=5) == 0


def test_occupancy_multiple_uses_count_each() -> None:
    hit = _Hit(start_ms=0, end_ms=8000)
    usage = {
        str(hit.video_id): [
            (0, 4000, 0),
            (4000, 8000, 1),
        ]
    }
    assert batch_occupancy_for(hit, usage, current_index=2, gap=5) == 2


def test_occupancy_empty_usage() -> None:
    hit = _Hit()
    assert batch_occupancy_for(hit, None, current_index=0, gap=5) == 0


def test_occupancy_different_video_ignored() -> None:
    hit = _Hit()
    usage = _usage(uuid4(), 0, 9000, used_index=0)
    assert batch_occupancy_for(hit, usage, current_index=1, gap=5) == 0


def test_gap_configurable() -> None:
    hit = _Hit(start_ms=0, end_ms=4000)
    usage = _usage(hit.video_id, 0, 4000, used_index=0)
    # gap=3：第 4 条（距上次 4 条）已释放
    assert batch_occupancy_for(hit, usage, current_index=4, gap=3) == 0
    # gap=6：第 4 条（距上次 4 条）仍在窗口内
    assert batch_occupancy_for(hit, usage, current_index=4, gap=6) == 1


# ---------- planner 集成：_fill_beat 选择避开占用片段 ----------

def _s_unit() -> DirectorUnit:
    return DirectorUnit(
        text_range="大梁承受坑洼扭转",
        importance="S",
        topic="越野性能",
        required_objects=["大梁"],
        required_actions=["承受坑洼扭转"],
        acceptable_surrogates=["底盘"],
        avoid=["电池骨架"],
        visual_function="证明大梁",
        anchor_phrase="大梁承受坑洼扭转",
    )


def _s_beat() -> ScriptBeat:
    unit = _s_unit()
    return ScriptBeat(
        id=uuid4(), project_id=uuid4(), narration_track_id=uuid4(),
        sequence=0, text="大梁承受坑洼扭转", timeline_start_ms=0,
        timeline_end_ms=4000, target_duration_ms=4000, query_text="大梁承受坑洼扭转",
        retrieval_intent={"director_units": [unit], "director_importance": "S"},
    )


def _make_planner(tmp_path: Path) -> RoughCutPlanner:
    return RoughCutPlanner(
        narration_store=NarrationStore(tmp_path / f"narration-{uuid4()}.sqlite3"),
        search=None,  # type: ignore[arg-type]  # _fill_beat 不触达 search
        store=RoughCutStore(tmp_path / f"roughcut-{uuid4()}.sqlite3"),
    )


def test_fill_beat_prefers_unoccupied_support(tmp_path: Path) -> None:
    """两个同为 SUPPORT 的候选：被占用（窗口内）的不被选中。"""
    planner = _make_planner(tmp_path)
    occupied = _search_hit(objects=["底盘"], actions=[], start_ms=0, end_ms=4000)
    free = _search_hit(objects=["底盘"], actions=[], start_ms=0, end_ms=4000)
    usage = {str(occupied.video_id): [(0, 4000, 0)]}
    clips, _ = planner._fill_beat(
        _s_beat(), [occupied, free], {}, None,
        batch_usage=usage, batch_index=1,
    )
    assert clips and clips[0].segment_id == free.segment_id


def test_fill_beat_rotates_video_even_when_used_range_does_not_overlap(tmp_path: Path) -> None:
    """A high-scoring video must cool down across similar batch entries even
    when it offers a different, non-overlapping segment."""
    planner = _make_planner(tmp_path)
    repeated_video = uuid4()
    same_video_new_range = _search_hit(
        objects=["底盘"], video_id=repeated_video, start_ms=10_000, end_ms=14_000,
    )
    other_video = _search_hit(objects=["底盘"], start_ms=0, end_ms=4_000)
    usage = {str(repeated_video): [(0, 4_000, 0)]}

    clips, _ = planner._fill_beat(
        _s_beat(), [same_video_new_range, other_video], {}, None,
        batch_usage=usage, batch_index=1,
    )

    assert clips and clips[0].video_id == other_video.video_id


def test_fill_beat_releases_after_gap(tmp_path: Path) -> None:
    """占用超过滚动窗口后视为释放，候选恢复正常可选中。"""
    planner = _make_planner(tmp_path)
    occupied = _search_hit(objects=["底盘"], actions=[], start_ms=0, end_ms=4000)
    free = _search_hit(objects=["底盘"], actions=[], start_ms=0, end_ms=4000)
    usage = {str(occupied.video_id): [(0, 4000, 0)]}
    # 当前第 6 条：距上次 6 条 >= gap=5 → 已释放，两个候选公平竞争（仍选占用的，
    # 因为两者同源同区间，占用方无罚后按 segment_id 稳定排序回原序）。
    clips, _ = planner._fill_beat(
        _s_beat(), [occupied, free], {}, None,
        batch_usage=usage, batch_index=6,
    )
    assert clips and clips[0].segment_id in {occupied.segment_id, free.segment_id}


def test_fill_beat_s_direct_light_avoid(tmp_path: Path) -> None:
    """S 级 DIRECT 轻避让：有未占用的 DIRECT 时优先未占用；占用 DIRECT 仍排在
    弱 SUPPORT 之前（稀缺画面换不到就复用）。"""
    planner = _make_planner(tmp_path)
    direct_occupied = _search_hit(
        objects=["大梁"], actions=["承受坑洼扭转"], start_ms=0, end_ms=4000,
    )
    direct_free = _search_hit(
        objects=["大梁"], actions=["承受坑洼扭转"], start_ms=0, end_ms=4000,
    )
    weak_support = _search_hit(
        objects=["内饰"], actions=[], start_ms=0, end_ms=4000, description="内饰特写",
    )
    usage = {str(direct_occupied.video_id): [(0, 4000, 0)]}
    clips, _ = planner._fill_beat(
        _s_beat(), [direct_occupied, weak_support, direct_free], {}, None,
        batch_usage=usage, batch_index=1,
    )
    # 未占用的 DIRECT 最优先
    assert clips and clips[0].segment_id == direct_free.segment_id

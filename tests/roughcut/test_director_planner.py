from pathlib import Path
from uuid import UUID, uuid4

import pytest

from clipatlas.director.analyzer import script_hash
from clipatlas.director.models import DirectorAnalysis, DirectorUnit
from clipatlas.director.service import DirectorService
from clipatlas.director.store import DirectorCacheStore
from clipatlas.domain.models import AnnotationOrigin, SemanticAnnotation
from clipatlas.retrieval.search import SemanticSearchHit
from clipatlas.roughcut.models import ScriptBeat
from clipatlas.roughcut.planner import RoughCutPlanner
from clipatlas.roughcut.store import RoughCutStore
from clipatlas.rules.models import ProjectRule, ProjectRulePack, RuleKind, RulePackStatus
from clipatlas.speech.models import (
    NarrationSourceMode,
    NarrationTrack,
    NarrationUnit,
    TimingQuality,
)
from clipatlas.speech.store import NarrationStore


class FakeDirectorAnalyzer:
    prompt_version = "director-test"
    rules_revision = "rules-test"

    def __init__(self, units: list[DirectorUnit]) -> None:
        self._units = units

    def _empty_analysis(self, text: str) -> DirectorAnalysis:
        return DirectorAnalysis(
            script_text=text,
            script_hash=script_hash(text),
            prompt_version=self.prompt_version,
            rules_revision=self.rules_revision,
            units=[],
        )

    async def analyze(self, text: str) -> DirectorAnalysis:
        return self._empty_analysis(text).model_copy(update={"units": self._units})


class FakeSearch:
    def project_video_ids(self, project_id: UUID) -> list[UUID]:
        return list({hit.video_id for hits in self.results.values() for hit in hits})

    def __init__(self, results: dict[str, list[SemanticSearchHit]]) -> None:
        self.results = results
        self.calls: list[tuple[str, int, list[UUID] | None]] = []

    async def search(self, query, limit=10, video_ids=None):
        self.calls.append((query, limit, video_ids))
        for key, hits in self.results.items():
            if query == key or query.startswith(key):
                return list(hits)[:limit]
        return []


def _hit(
    *,
    description: str,
    objects: list[str] | None = None,
    actions: list[str] | None = None,
    score: float = 0.8,
    start_ms: int = 0,
    end_ms: int = 9000,
) -> SemanticSearchHit:
    segment_id = uuid4()
    annotation = SemanticAnnotation(
        segment_id=segment_id,
        origin=AnnotationOrigin.AI,
        provider="test",
        description=description,
        objects=objects or [],
        actions=actions or [],
        confidence=0.9,
    )
    return SemanticSearchHit(
        segment_id=segment_id,
        video_id=uuid4(),
        source_uri="file:///source.mp4",
        source_start_ms=start_ms,
        source_end_ms=end_ms,
        score=score,
        effective_description=description,
        annotation=annotation,
        embedding_provider="test",
        embedding_model="test-model",
        embedding_dimensions=3,
    )


def _narration(
    tmp_path: Path,
    units: list[tuple[str, int, int]],
    *,
    duration_ms: int,
) -> tuple[NarrationStore, UUID]:
    store = NarrationStore(tmp_path / f"narration-{uuid4()}.sqlite3")
    project_id = uuid4()
    track = NarrationTrack(
        project_id=project_id,
        source_mode=NarrationSourceMode.TTS,
        script_hash="script",
        duration_ms=duration_ms,
        timing_quality=TimingQuality.UNIT_EXACT,
    )
    store.save_track(track)
    for sequence, (text, start_ms, end_ms) in enumerate(units):
        store.save_unit(
            NarrationUnit(
                track_id=track.id,
                sequence=sequence,
                text=text,
                text_hash=f"hash-{sequence}",
                start_ms=start_ms,
                end_ms=end_ms,
            )
        )
    assert store.activate_track(project_id, track.id) is True
    return store, project_id


def _planner(
    tmp_path: Path,
    narration_store: NarrationStore,
    search: FakeSearch,
    *,
    director: DirectorService | None = None,
) -> tuple[RoughCutPlanner, RoughCutStore]:
    rough_cut_store = RoughCutStore(tmp_path / f"roughcut-{uuid4()}.sqlite3")
    return (
        RoughCutPlanner(
            narration_store=narration_store,
            search=search,
            store=rough_cut_store,
            director=director,
        ),
        rough_cut_store,
    )


def _director(tmp_path: Path, units: list[DirectorUnit]) -> DirectorService:
    return DirectorService(
        analyzer=FakeDirectorAnalyzer(units),  # type: ignore[arg-type]
        store=DirectorCacheStore(tmp_path / f"director-{uuid4()}.db"),
    )


def _s_unit(text_range: str) -> DirectorUnit:
    return DirectorUnit(
        text_range=text_range,
        importance="S",
        topic="越野性能",
        required_objects=["大梁"],
        required_actions=["承受坑洼扭转"],
        acceptable_surrogates=["底盘大梁结构图"],
        avoid=["电池骨架"],
        visual_function="证明大梁",
        anchor_phrase=text_range,
    )


def _b_unit(text_range: str) -> DirectorUnit:
    return DirectorUnit(
        text_range=text_range,
        importance="B",
        topic="转折强调",
        required_subjects=[],
        required_objects=[],
        required_actions=[],
        acceptable_surrogates=[],
        avoid=[],
        visual_function="连接",
        anchor_phrase="",
    )


# ---------- pure helper behaviour ----------


def _beat(text: str, index: int = 0) -> ScriptBeat:
    return ScriptBeat(
        project_id=uuid4(),
        narration_track_id=uuid4(),
        sequence=index,
        text=text,
        timeline_start_ms=index * 1000,
        timeline_end_ms=(index + 1) * 1000,
        target_duration_ms=1000,
        query_text=text,
    )


def test_attach_director_units_sets_importance_and_units() -> None:
    unit = _s_unit("性能段").model_copy(update={"beat_range": (0, 0)})
    beats = RoughCutPlanner._attach_director_units([_beat("性能段")], [unit])

    assert beats[0].retrieval_intent["director_importance"] == "S"
    assert beats[0].retrieval_intent["director_units"][0]["required_objects"] == ["大梁"]


def test_director_cache_identity_is_project_and_rule_content_scoped() -> None:
    project_a, project_b = uuid4(), uuid4()
    pack_a = ProjectRulePack(
        project_id=project_a, revision=1, status=RulePackStatus.ACTIVE,
        rules=[ProjectRule(kind=RuleKind.SEMANTIC_HINT, hint="重点检索大梁")],
    )
    pack_b = ProjectRulePack(
        project_id=project_b, revision=1, status=RulePackStatus.ACTIVE,
        rules=[ProjectRule(kind=RuleKind.SEMANTIC_HINT, hint="重点检索座椅")],
    )

    first = RoughCutPlanner._director_rule_identity(project_a, pack_a)
    assert first == RoughCutPlanner._director_rule_identity(project_a, pack_a)
    assert first != RoughCutPlanner._director_rule_identity(project_b, pack_b)
    changed = pack_a.model_copy(update={
        "rules": [ProjectRule(kind=RuleKind.SEMANTIC_HINT, hint="重点检索车身")],
    })
    assert first != RoughCutPlanner._director_rule_identity(project_a, changed)


def test_pure_b_sentence_keeps_its_cut_boundary() -> None:
    b_unit = _b_unit("意义在此").model_copy(update={"beat_range": (1, 1)})
    s_unit = _s_unit("性能段").model_copy(update={"beat_range": (0, 0)})
    beats = RoughCutPlanner._attach_director_units(
        [_beat("性能段", 0), _beat("意义在此", 1)], [s_unit, b_unit]
    )
    merged = RoughCutPlanner._merge_director_beats(beats)

    assert len(merged) == 2
    assert [beat.text for beat in merged] == ["性能段", "意义在此"]
    assert [beat.timeline_end_ms for beat in merged] == [1000, 2000]
    assert [beat.sequence for beat in merged] == [0, 1]


def test_same_s_topic_keeps_complete_sentence_boundaries() -> None:
    """Director topic continuity must not erase grammatical sentence cuts."""
    unit = _s_unit("性能段").model_copy(update={"beat_range": (0, 2)})
    beats = RoughCutPlanner._attach_director_units(
        [_beat("第一句", 0), _beat("第二句", 1), _beat("第三句", 2)], [unit]
    )
    merged = RoughCutPlanner._merge_director_beats(beats)

    assert len(merged) == 3
    assert [beat.text for beat in merged] == ["第一句", "第二句", "第三句"]
    assert [beat.timeline_end_ms for beat in merged] == [1000, 2000, 3000]


def test_same_director_unit_builds_one_visual_beat_without_erasing_sentences() -> None:
    unit = _s_unit("第一句。第二句。").model_copy(update={"beat_range": (0, 1)})
    sentence_beats = RoughCutPlanner._attach_director_units(
        [_beat("第一句。", 0), _beat("第二句。", 1)], [unit]
    )

    visual_beats = RoughCutPlanner._build_visual_beats(sentence_beats)

    assert len(sentence_beats) == 2
    assert len(visual_beats) == 1
    assert visual_beats[0].id == sentence_beats[0].id
    assert visual_beats[0].text == "第一句。\n第二句。"
    assert visual_beats[0].target_duration_ms == 2000
    assert visual_beats[0].retrieval_intent["visual_beat_sequences"] == [0, 1]


def test_visual_beat_uses_conservative_window_below_thirty_second_ceiling() -> None:
    unit = _s_unit("完整论述").model_copy(update={"beat_range": (0, 2)})
    beats = [
        _beat("第一句。", 0).model_copy(update={
            "timeline_start_ms": 0, "timeline_end_ms": 12_000,
            "target_duration_ms": 12_000,
        }),
        _beat("第二句。", 1).model_copy(update={
            "timeline_start_ms": 12_000, "timeline_end_ms": 24_000,
            "target_duration_ms": 12_000,
        }),
        _beat("第三句。", 2).model_copy(update={
            "timeline_start_ms": 24_000, "timeline_end_ms": 36_000,
            "target_duration_ms": 12_000,
        }),
    ]
    beats = RoughCutPlanner._attach_director_units(beats, [unit])

    visual_beats = RoughCutPlanner._build_visual_beats(beats)

    assert [beat.target_duration_ms for beat in visual_beats] == [12_000, 12_000, 12_000]


def test_sentence_boundary_cuts_across_topics() -> None:
    """句号断句：卖点改变或跨等级时必须切镜，不跨卖点合并。"""
    s_unit = _s_unit("性能段").model_copy(update={"beat_range": (0, 0)})
    a_unit = DirectorUnit(
        text_range="参数段", importance="A", topic="参数说明",
        required_subjects=[], required_objects=["车身"], required_actions=[],
        acceptable_surrogates=[], avoid=[],
    ).model_copy(update={"beat_range": (1, 1)})
    beats = RoughCutPlanner._attach_director_units(
        [_beat("性能段", 0), _beat("参数段", 1)], [s_unit, a_unit]
    )
    merged = RoughCutPlanner._merge_director_beats(beats)

    assert len(merged) == 2
    assert merged[0].text == "性能段"
    assert merged[1].text == "参数段"


def test_reject_filters_avoid_hits() -> None:
    unit = _s_unit("性能段")
    good = _hit(description="大梁承受扭转", objects=["大梁"], actions=["承受扭转"])
    wrong = _hit(description="电池骨架特写", objects=["电池骨架"])
    kept = RoughCutPlanner._reject_director_mismatches([good, wrong], [unit], [])

    assert kept == [good]


def test_fit_priority_ranks_direct_before_support() -> None:
    unit = _s_unit("性能段")
    direct = _hit(description="大梁承受坑洼扭转", objects=["大梁"], actions=["承受坑洼扭转"])
    support = _hit(description="底盘大梁结构示意图")
    unknown = _hit(description="主持人讲话")

    assert (RoughCutPlanner._fit_priority(direct, [unit])
            < RoughCutPlanner._fit_priority(support, [unit])
            < RoughCutPlanner._fit_priority(unknown, [unit]))


# ---------- end-to-end ----------


@pytest.mark.asyncio
async def test_plan_uses_one_visual_window_for_multi_sentence_director_unit(
    tmp_path: Path,
) -> None:
    narration_store, project_id = _narration(
        tmp_path,
        [("央视镜头进入会场。", 0, 4000), ("镜头对准泰钽700。", 4000, 8000)],
        duration_ms=8000,
    )
    hit = _hit(
        description="央视镜头对准泰钽700",
        objects=["泰钽700"], actions=["镜头对准车辆"], end_ms=10_000,
    )
    search = FakeSearch({"央视镜头进入会场。": [hit]})
    unit = DirectorUnit(
        text_range="央视镜头进入会场。镜头对准泰钽700。",
        importance="S", topic="央视直播产品亮相",
        required_objects=["泰钽700"], required_actions=["镜头对准车辆"],
        acceptable_surrogates=[], avoid=[], visual_function="证明央视直播亮相",
        anchor_phrase="镜头对准泰钽700",
    )
    planner, _ = _planner(
        tmp_path, narration_store, search, director=_director(tmp_path, [unit]),
    )

    plan = await planner.create_plan(project_id)

    assert len(plan.beats) == 2
    assert len(plan.subtitles) == 2
    assert len(plan.clips) == 1
    assert (plan.clips[0].timeline_in_ms, plan.clips[0].timeline_out_ms) == (0, 8000)
    assert search.calls[0][0] == "央视镜头进入会场。\n镜头对准泰钽700。"


@pytest.mark.asyncio
async def test_plan_prefers_direct_and_keeps_b_sentence_boundary(tmp_path: Path) -> None:
    narration_store, project_id = _narration(
        tmp_path,
        [("第一道是性能。大梁承受坑洼扭转。", 0, 6000), ("这件事的意义正在这里。", 6000, 8000)],
        duration_ms=8000,
    )
    search = FakeSearch({
        "第一道是性能。大梁承受坑洼扭转。": [
            _hit(description="大梁承受扭转", objects=["大梁"], actions=["承受扭转"]),
            _hit(description="电池骨架特写", objects=["电池骨架"]),
        ],
    })
    director = _director(tmp_path, [_s_unit("第一道是性能。大梁承受坑洼扭转。"), _b_unit("这件事的意义正在这里。")])
    planner, _ = _planner(tmp_path, narration_store, search, director=director)

    plan = await planner.create_plan(project_id)

    # S 与 B 保持完整句切点；B 延续 S 的视觉线程。
    assert len(plan.beats) == 2
    assert plan.beats[0].retrieval_intent.get("director_importance") == "S"
    assert len(plan.clips) == 2
    clip = plan.clips[0]
    assert (clip.timeline_in_ms, clip.timeline_out_ms) == (0, 6000)
    assert "电池骨架" not in clip.selection_reason
    assert "大梁" in clip.selection_reason
    assert plan.clips[1].video_id == clip.video_id
    assert (plan.clips[1].timeline_in_ms, plan.clips[1].timeline_out_ms) == (6000, 8000)


@pytest.mark.asyncio
async def test_plan_without_director_keeps_previous_behaviour(tmp_path: Path) -> None:
    narration_store, project_id = _narration(
        tmp_path,
        [("第一句", 0, 5000), ("第二句", 5000, 9000)],
        duration_ms=9000,
    )
    search = FakeSearch({
        "第一句": [_hit(description="素材A", start_ms=0, end_ms=9000)],
        "第二句": [_hit(description="素材B", start_ms=0, end_ms=9000)],
    })
    planner, _ = _planner(tmp_path, narration_store, search, director=None)

    plan = await planner.create_plan(project_id)

    assert len(plan.beats) == 2
    assert len(plan.clips) == 2
    assert all(clip.schedule_level == "exact" for clip in plan.clips)


@pytest.mark.asyncio
async def test_director_failure_degrades_to_local_planning_instead_of_stopping(tmp_path: Path) -> None:
    class FailingDirector:
        enabled = True
        async def analyze_cached(self, *args, **kwargs):
            raise RuntimeError("provider unavailable")

    narration_store, project_id = _narration(
        tmp_path, [("北京越野继续前进。", 0, 4000)], duration_ms=4000,
    )
    search = FakeSearch({"北京越野继续前进。": [
        _hit(description="北京越野车辆行驶", end_ms=5000),
    ]})
    planner, _ = _planner(tmp_path, narration_store, search, director=FailingDirector())
    plan = await planner.create_plan(project_id)
    assert plan.clips[-1].timeline_out_ms == 4000
    assert any("Director 分析不可用" in warning for warning in plan.warnings)

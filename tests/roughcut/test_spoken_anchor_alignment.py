from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from clipatlas.director.models import DirectorUnit
from clipatlas.domain.models import AnnotationOrigin, SemanticAnnotation
from clipatlas.roughcut.evidence import (
    exact_spoken_anchor_offset_ms,
    source_window,
    spoken_anchor_offset_ms,
)
from clipatlas.roughcut.planner import RoughCutPlanner
from clipatlas.roughcut.store import RoughCutStore
from clipatlas.speech.models import (
    NarrationSourceMode,
    NarrationTrack,
    NarrationUnit,
    NarrationWordTiming,
    TimingQuality,
)
from clipatlas.speech.store import NarrationStore


class _SingleHitSearch:
    def __init__(self, hit: SimpleNamespace) -> None:
        self._hit = hit

    def project_video_ids(self, project_id: UUID) -> list[UUID]:
        del project_id
        return [self._hit.video_id]

    async def search(
        self,
        query: str,
        limit: int = 10,
        video_ids: list[UUID] | None = None,
    ) -> list[SimpleNamespace]:
        del query, limit, video_ids
        return [self._hit]


class _AnchorDirector:
    enabled = True

    def __init__(self, unit: DirectorUnit) -> None:
        self._unit = unit

    async def analyze_cached(self, script_text: str, **kwargs) -> SimpleNamespace:
        del script_text, kwargs
        return SimpleNamespace(
            contract_issues=[],
            units=[self._unit],
            requirements=[],
        )

    def map_units(self, beats, analysis) -> list[DirectorUnit]:
        del analysis
        return [self._unit.model_copy(update={"beat_range": (0, len(beats) - 1)})]


def _hit(*, anchor_start_ms: int, anchor_end_ms: int):
    annotation = SemanticAnnotation(
        segment_id=uuid4(),
        origin=AnnotationOrigin.AI,
        description="泰钽700在贵州盘山路向上爬坡",
        characters=["泰钽700"],
        actions=["爬坡"],
    )
    return SimpleNamespace(
        segment_id=annotation.segment_id,
        video_id=uuid4(),
        source_uri="file:///footage/guizhou.mp4",
        source_start_ms=0,
        source_end_ms=12_000,
        score=0.95,
        anchor_start_ms=anchor_start_ms,
        anchor_end_ms=anchor_end_ms,
        safe_start_ms=None,
        safe_end_ms=None,
        annotation=annotation,
    )


def test_spoken_anchor_offset_tracks_phrase_position_inside_sentence():
    text = "泰钽700在贵州盘山路向上爬。"
    offset = spoken_anchor_offset_ms(text, "贵州盘山路", 10_000)

    assert offset is not None
    assert 4_000 <= offset <= 8_000


def test_exact_spoken_anchor_uses_provider_word_timing_across_tokens():
    unit_id = uuid4()
    timings = [
        NarrationWordTiming(unit_id=unit_id, sequence=0, word="泰钽700", start_ms=0, end_ms=1200),
        NarrationWordTiming(unit_id=unit_id, sequence=1, word="在", start_ms=1200, end_ms=1500),
        NarrationWordTiming(unit_id=unit_id, sequence=2, word="贵州", start_ms=1800, end_ms=2600),
        NarrationWordTiming(unit_id=unit_id, sequence=3, word="盘山路", start_ms=2600, end_ms=4000),
        NarrationWordTiming(unit_id=unit_id, sequence=4, word="向上爬", start_ms=4000, end_ms=5200),
    ]

    offset = exact_spoken_anchor_offset_ms(
        "贵州盘山路", beat_start_ms=0, beat_end_ms=10_000, word_timings=timings,
    )

    assert offset == 2900


def test_exact_spoken_anchor_is_relative_to_visual_beat_start():
    unit_id = uuid4()
    timings = [
        NarrationWordTiming(unit_id=unit_id, sequence=0, word="贵州", start_ms=11_800, end_ms=12_600),
        NarrationWordTiming(unit_id=unit_id, sequence=1, word="盘山路", start_ms=12_600, end_ms=14_000),
    ]

    offset = exact_spoken_anchor_offset_ms(
        "贵州盘山路", beat_start_ms=10_000, beat_end_ms=20_000, word_timings=timings,
    )

    assert offset == 2900


def test_source_window_aligns_evidence_anchor_to_spoken_anchor_offset():
    hit = _hit(anchor_start_ms=6_000, anchor_end_ms=8_000)

    start, end = source_window(
        hit,
        10_000,
        anchor_target_offset_ms=6_000,
    )

    # Evidence centre is 7000ms. To make it appear 6000ms into the spoken
    # sentence, the selected source window should start near 1000ms.
    assert (start, end) == (1_000, 11_000)
    assert start <= hit.anchor_start_ms < hit.anchor_end_ms <= end


def test_source_window_prefers_provider_target_over_text_position_estimate():
    annotation = SemanticAnnotation(
        segment_id=uuid4(), origin=AnnotationOrigin.AI, description="贵州盘山路爬坡",
    )
    hit = SimpleNamespace(
        source_start_ms=0,
        source_end_ms=12_000,
        anchor_start_ms=6_000,
        anchor_end_ms=8_000,
        safe_start_ms=None,
        safe_end_ms=None,
        spoken_anchor_target_ms=1_000,
        annotation=annotation,
    )
    unit = DirectorUnit(
        text_range="泰钽700继续行驶，最后才说贵州盘山路。",
        importance="S",
        topic="贵州爬坡",
        anchor_phrase="贵州盘山路",
        required_subjects=["泰钽700"],
    )

    start, end = source_window(hit, 6_000, [unit])

    # Existing hit timing says the spoken anchor is 1s into this beat. Evidence
    # centre is 7s, so the legal source window should begin at 6s. A pure text
    # position estimate would put the late phrase much closer to the end.
    assert (start, end) == (6_000, 12_000)


def test_source_window_uses_director_anchor_phrase_without_extra_planner_api():
    hit = _hit(anchor_start_ms=6_000, anchor_end_ms=8_000)
    unit = DirectorUnit(
        text_range="泰钽700在贵州盘山路向上爬。",
        importance="S",
        topic="贵州爬坡",
        anchor_phrase="贵州盘山路",
        required_subjects=["泰钽700"],
        required_actions=["爬坡"],
    )

    start, end = source_window(hit, 10_000, [unit])

    assert 0 < start <= 2_000
    assert end == start + 10_000
    assert start <= hit.anchor_start_ms < hit.anchor_end_ms <= end


def test_invalid_or_missing_anchor_phrase_does_not_invent_timing():
    assert spoken_anchor_offset_ms("完整句。", "不存在", 5_000) is None
    assert spoken_anchor_offset_ms("完整句。", None, 5_000) is None
    assert exact_spoken_anchor_offset_ms(
        "不存在", beat_start_ms=0, beat_end_ms=5_000, word_timings=[],
    ) is None


@pytest.mark.asyncio
async def test_provider_word_timing_changes_final_rough_cut_source_window(tmp_path: Path) -> None:
    project_id = uuid4()
    narration_store = NarrationStore(tmp_path / "narration.sqlite3")
    text = "泰钽700在贵州盘山路向上爬。"
    track = NarrationTrack(
        project_id=project_id,
        source_mode=NarrationSourceMode.TTS,
        script_hash="word-timing-regression",
        duration_ms=6_000,
        timing_quality=TimingQuality.WORD_EXACT,
    )
    narration_store.save_track(track)
    narration_unit = NarrationUnit(
        track_id=track.id,
        sequence=0,
        text=text,
        text_hash="unit-0",
        start_ms=0,
        end_ms=6_000,
    )
    narration_store.save_unit(narration_unit)
    assert narration_store.activate_track(project_id, track.id) is True

    director_unit = DirectorUnit(
        text_range=text,
        importance="S",
        topic="贵州爬坡",
        anchor_phrase="贵州盘山路",
        required_subjects=["泰钽700"],
        required_objects=[],
        required_actions=[],
        acceptable_surrogates=[],
        avoid=[],
        visual_function="对齐贵州盘山路重点画面",
    )
    search = _SingleHitSearch(_hit(anchor_start_ms=6_000, anchor_end_ms=8_000))
    planner = RoughCutPlanner(
        narration_store=narration_store,
        search=search,
        store=RoughCutStore(tmp_path / "roughcut.sqlite3"),
        director=_AnchorDirector(director_unit),  # type: ignore[arg-type]
    )

    narration_store.save_word_timings([
        NarrationWordTiming(
            unit_id=narration_unit.id,
            sequence=0,
            word="贵州盘山路",
            start_ms=500,
            end_ms=1_500,
        )
    ])
    early = await planner.create_plan(project_id, persist=False)

    narration_store.save_word_timings([
        NarrationWordTiming(
            unit_id=narration_unit.id,
            sequence=0,
            word="贵州盘山路",
            start_ms=4_500,
            end_ms=5_500,
        )
    ])
    late = await planner.create_plan(project_id, persist=False)

    assert early.clips[0].source_in_ms == 6_000
    assert late.clips[0].source_in_ms == 2_000
    assert early.clips[0].source_in_ms != late.clips[0].source_in_ms

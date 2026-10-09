from uuid import uuid4

from clipatlas.director.mapper import map_units_to_beats
from clipatlas.director.models import DirectorUnit
from clipatlas.roughcut.models import ScriptBeat


def _beat(text: str, index: int) -> ScriptBeat:
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


def _unit(text_range: str, importance: str = "S") -> DirectorUnit:
    return DirectorUnit(
        text_range=text_range,
        importance=importance,  # type: ignore[arg-type]
        topic="t",
        required_objects=["大梁"],
    )


def test_exact_span_maps_to_single_beat() -> None:
    beats = [_beat("第一道是性能", 0), _beat("这个车是带大梁的", 1), _beat("意义在此", 2)]
    units = map_units_to_beats(beats, [_unit("第一道是性能")])

    assert units[0].beat_range == (0, 0)


def test_span_across_beats_maps_to_inclusive_range() -> None:
    beats = [_beat("第一道是性能", 0), _beat("这个车是带大梁的", 1), _beat("遇到大坑拧大梁", 2)]
    units = map_units_to_beats(beats, [_unit("这个车是带大梁的。遇到大坑拧大梁")])

    assert units[0].beat_range == (1, 2)


def test_whitespace_variation_is_ignored() -> None:
    beats = [_beat("第一道 是 性能", 0), _beat("这个车是带大梁的", 1)]
    units = map_units_to_beats(beats, [_unit("第一道是性能")])

    assert units[0].beat_range == (0, 0)


def test_sentence_fallback_when_full_span_missing() -> None:
    beats = [_beat("第一道是性能", 0), _beat("这个车是带大梁的", 1)]
    # 全 span 带插入词，无法整体命中；句子级命中两个 beat。
    units = map_units_to_beats(beats, [_unit("第一道是性能，然后这个车是带大梁的")])

    assert units[0].beat_range == (0, 1)


def test_semicolon_remains_inside_one_sentence_for_fallback_mapping() -> None:
    beats = [_beat("城市通勤很从容；到了山里也能继续前进", 0)]
    units = map_units_to_beats(beats, [_unit("城市通勤很从容；到了山里也能继续前进")])
    assert units[0].beat_range == (0, 0)


def test_unmappable_unit_keeps_none_range() -> None:
    beats = [_beat("第一道是性能", 0)]
    units = map_units_to_beats(beats, [_unit("完全没出现的句子")])

    assert units[0].beat_range is None


def test_empty_beats_leave_units_untouched() -> None:
    units = map_units_to_beats([], [_unit("第一道是性能")])

    assert units[0].beat_range is None

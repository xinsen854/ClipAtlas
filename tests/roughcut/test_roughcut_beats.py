from uuid import uuid4

import pytest

from clipatlas.roughcut.beats import BeatBuilder
from clipatlas.roughcut.errors import RoughCutTimingError
from clipatlas.speech.models import (
    NarrationSourceMode,
    NarrationTrack,
    NarrationUnit,
    TimingQuality,
)


def _track(
    *,
    duration_ms: int = 2500,
    timing_quality: TimingQuality = TimingQuality.UNIT_EXACT,
    source_mode: NarrationSourceMode = NarrationSourceMode.TTS,
) -> NarrationTrack:
    return NarrationTrack(
        project_id=uuid4(),
        source_mode=source_mode,
        script_hash="script",
        duration_ms=duration_ms,
        timing_quality=timing_quality,
    )


def _unit(
    track: NarrationTrack,
    *,
    sequence: int,
    text: str,
    start_ms: int | None,
    end_ms: int | None,
) -> NarrationUnit:
    return NarrationUnit(
        track_id=track.id,
        sequence=sequence,
        text=text,
        text_hash=f"hash-{sequence}",
        start_ms=start_ms,
        end_ms=end_ms,
    )


def test_build_splits_internal_silence_and_owns_leading_and_trailing_silence() -> None:
    track = _track(duration_ms=2500)
    units = [
        _unit(track, sequence=0, text="第一句", start_ms=200, end_ms=1000),
        _unit(track, sequence=1, text="第二句", start_ms=1400, end_ms=2200),
    ]

    beats = BeatBuilder().build(track, units)

    assert [(beat.timeline_start_ms, beat.timeline_end_ms) for beat in beats] == [
        (0, 1200),
        (1200, 2500),
    ]
    assert [beat.target_duration_ms for beat in beats] == [1200, 1300]
    assert [beat.query_text for beat in beats] == ["第一句", "第二句"]
    assert all(beat.project_id == track.project_id for beat in beats)
    assert all(beat.narration_track_id == track.id for beat in beats)


def test_build_keeps_contiguous_internal_boundary() -> None:
    track = _track(duration_ms=2200)
    units = [
        _unit(track, sequence=0, text="A", start_ms=100, end_ms=1000),
        _unit(track, sequence=1, text="B", start_ms=1000, end_ms=2000),
    ]

    beats = BeatBuilder().build(track, units)

    assert [(beat.timeline_start_ms, beat.timeline_end_ms) for beat in beats] == [
        (0, 1000),
        (1000, 2200),
    ]


def test_build_orders_units_by_sequence_deterministically() -> None:
    track = _track(duration_ms=2000)
    first = _unit(track, sequence=0, text="先", start_ms=0, end_ms=900)
    second = _unit(track, sequence=1, text="后", start_ms=1100, end_ms=2000)

    beats = BeatBuilder().build(track, [second, first])

    assert [beat.sequence for beat in beats] == [0, 1]
    assert [beat.text for beat in beats] == ["先", "后"]
    assert beats[0].timeline_end_ms == beats[1].timeline_start_ms == 1000


def test_build_track_only_imported_narration_requires_alignment() -> None:
    track = _track(
        duration_ms=2500,
        timing_quality=TimingQuality.TRACK_ONLY,
        source_mode=NarrationSourceMode.IMPORTED,
    )
    units = [
        _unit(track, sequence=0, text="第一句", start_ms=None, end_ms=None),
        _unit(track, sequence=1, text="第二句", start_ms=None, end_ms=None),
    ]

    with pytest.raises(RoughCutTimingError, match="track_only"):
        BeatBuilder().build(track, units)
    assert all(unit.start_ms is None and unit.end_ms is None for unit in units)


@pytest.mark.parametrize(
    "timing_quality,source_mode",
    [
        (TimingQuality.TRACK_ONLY, NarrationSourceMode.TTS),
    ],
)
def test_build_rejects_unsupported_non_authoritative_timing(
    timing_quality: TimingQuality,
    source_mode: NarrationSourceMode,
) -> None:
    track = _track(timing_quality=timing_quality, source_mode=source_mode)
    units = [_unit(track, sequence=0, text="一句", start_ms=0, end_ms=2500)]

    with pytest.raises(RoughCutTimingError):
        BeatBuilder().build(track, units)


def test_build_rejects_untimed_units() -> None:
    track = _track()
    units = [_unit(track, sequence=0, text="一句", start_ms=None, end_ms=None)]

    with pytest.raises(RoughCutTimingError):
        BeatBuilder().build(track, units)


def test_build_rejects_overlapping_units() -> None:
    track = _track(duration_ms=2000)
    units = [
        _unit(track, sequence=0, text="A", start_ms=0, end_ms=1100),
        _unit(track, sequence=1, text="B", start_ms=1000, end_ms=2000),
    ]

    with pytest.raises(RoughCutTimingError):
        BeatBuilder().build(track, units)


def test_build_rejects_unit_ending_after_track_duration() -> None:
    track = _track(duration_ms=2000)
    units = [_unit(track, sequence=0, text="A", start_ms=100, end_ms=2100)]

    with pytest.raises(RoughCutTimingError):
        BeatBuilder().build(track, units)


def test_build_rejects_empty_text() -> None:
    track = _track(duration_ms=1000)
    units = [_unit(track, sequence=0, text="   ", start_ms=0, end_ms=1000)]

    with pytest.raises(RoughCutTimingError):
        BeatBuilder().build(track, units)


def test_build_rejects_empty_unit_list() -> None:
    track = _track(duration_ms=1000)

    with pytest.raises(RoughCutTimingError):
        BeatBuilder().build(track, [])


def test_build_accepts_word_exact_and_aligned_unit_windows() -> None:
    for timing_quality in (TimingQuality.WORD_EXACT, TimingQuality.ALIGNED, TimingQuality.ESTIMATED):
        track = _track(duration_ms=1000, timing_quality=timing_quality)
        units = [_unit(track, sequence=0, text="一句", start_ms=0, end_ms=1000)]

        beats = BeatBuilder().build(track, units)

        assert [(beat.timeline_start_ms, beat.timeline_end_ms) for beat in beats] == [
            (0, 1000)
        ]


def test_complete_sentence_is_not_split_by_eight_second_shot_preference() -> None:
    track = _track(duration_ms=12_000)
    units = [
        _unit(track, sequence=0, text="这是一句较长的完整表达，", start_ms=0, end_ms=6000),
        _unit(track, sequence=1, text="但它仍然要到句号才结束。", start_ms=6000, end_ms=12_000),
    ]
    beats = BeatBuilder().build(track, units)
    assert len(beats) == 1
    assert beats[0].target_duration_ms == 12_000


def test_semicolon_inside_sentence_does_not_create_a_visual_beat() -> None:
    track = _track(duration_ms=9000)
    units = [
        _unit(track, sequence=0, text="城市通勤很从容；", start_ms=0, end_ms=4500),
        _unit(track, sequence=1, text="到了山里也能继续前进。", start_ms=4500, end_ms=9000),
    ]
    assert len(BeatBuilder().build(track, units)) == 1

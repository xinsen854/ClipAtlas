"""Tests for rule-aware subtitle generation."""

from uuid import uuid4

import pytest

from clipatlas.roughcut.models import RoughCutSubtitle, ScriptBeat
from clipatlas.roughcut.subtitles import build_subtitles, merge_adjacent_identical, split_by_punctuation
from clipatlas.rules.models import ProjectRule, ProjectRulePack, RuleKind


def _beat(sequence, text, start_ms, end_ms) -> ScriptBeat:
    return ScriptBeat(
        project_id=uuid4(),
        narration_track_id=uuid4(),
        sequence=sequence,
        text=text,
        timeline_start_ms=start_ms,
        timeline_end_ms=end_ms,
        target_duration_ms=end_ms - start_ms,
        query_text=text,
    )


def _pack(*rules: ProjectRule) -> ProjectRulePack:
    return ProjectRulePack(project_id=uuid4(), revision=1, status="active", rules=list(rules))


def test_split_drops_punctuation_and_splits_segments() -> None:
    assert split_by_punctuation("第一句旁白。第二句！第三句？") == [
        "第一句旁白",
        "第二句",
        "第三句",
    ]
    # enumeration comma and quotes do not split, but are dropped
    assert split_by_punctuation("座舱采用“一舱三境”设计。") == ["座舱采用一舱三境设计"]
    assert split_by_punctuation("弥散、鼻吸双模式可同时满足四人供氧。") == [
        "弥散鼻吸双模式可同时满足四人供氧"
    ]
    assert split_by_punctuation("硬派越野，够硬也够糙——这就是它。") == [
        "硬派越野",
        "够硬也够糙",
        "这就是它",
    ]
    # spaces never split: model names stay together
    assert split_by_punctuation("泰钽700把华为乾崑智驾ADS 5.0 MAX装进了带大梁的非承载车身。") == [
        "泰钽700把华为乾崑智驾ADS 5.0",
        "MAX装进了带大梁的非承载车身",
    ]


def test_short_fragment_merges_into_neighbour() -> None:
    assert split_by_punctuation("出发了，走。") == ["出发了走"]


def test_subtitles_follow_beat_windows_with_proportional_timing() -> None:
    beats = [_beat(0, "第一句旁白。", 0, 4000), _beat(1, "第二句旁白。", 4000, 9000)]
    subtitles = build_subtitles(beats, None)
    assert [s.text for s in subtitles] == ["第一句旁白", "第二句旁白"]
    assert [(s.start_ms, s.end_ms) for s in subtitles] == [(0, 4000), (4000, 9000)]


def test_commas_split_a_beat_into_multiple_subtitles() -> None:
    beats = [_beat(0, "关上车门，任凭窗外风雨，车内自是一方清净。", 0, 9000)]
    subtitles = build_subtitles(beats, None)
    assert [s.text for s in subtitles] == ["关上车门", "任凭窗外风雨", "车内自是一方清净"]


def test_subtitle_replace_rule_applied_but_speech_untouched() -> None:
    pack = _pack(
        ProjectRule(kind=RuleKind.SUBTITLE_REPLACE, match="央视", replacement=""),
        ProjectRule(kind=RuleKind.SPEECH_SUPPRESS, match="机密", replacement=None),
    )
    beats = [_beat(0, "央视报道了这项技术，内容不涉及机密。", 0, 6000)]
    subtitles = build_subtitles(beats, pack)
    assert [s.text for s in subtitles] == ["报道了这项技术", "内容不涉及机密"]


def test_pronunciation_rule_does_not_change_subtitles() -> None:
    pack = _pack(ProjectRule(kind=RuleKind.PRONUNCIATION, match="泰钽700", replacement="泰钽七百"))
    beats = [_beat(0, "泰钽700登场。", 0, 3000)]
    subtitles = build_subtitles(beats, pack)
    assert subtitles[0].text == "泰钽700登场"


def test_fully_removed_subtitle_is_skipped() -> None:
    pack = _pack(ProjectRule(kind=RuleKind.SUBTITLE_REPLACE, match="央视", replacement=""))
    beats = [_beat(0, "央视", 0, 3000)]
    subtitles = build_subtitles(beats, pack)
    assert subtitles == []


def test_adjacent_identical_lines_merge() -> None:
    merged = merge_adjacent_identical(
        [
            RoughCutSubtitle(text="同一句", start_ms=0, end_ms=4000),
            RoughCutSubtitle(text="同一句", start_ms=4000, end_ms=8000),
            RoughCutSubtitle(text="另一句", start_ms=8000, end_ms=12000),
        ]
    )
    assert len(merged) == 2
    assert merged[0].start_ms == 0 and merged[0].end_ms == 8000

"""On-screen title card rules: punctuation stripping, line split, size tiers."""
from __future__ import annotations

from clipatlas.exports.jianying import (
    clean_title_text,
    split_title_lines,
    title_layout,
)


def test_clean_title_text_strips_punctuation_keeps_dots() -> None:
    assert clean_title_text("L2.5、L2.9？强制国标一出，全作废！") == "L2.5 L2.9 强制国标一出 全作废"
    assert clean_title_text("两个“第一” 华为乾崑为何能同时拿下高端与主流？") == "两个 第一 华为乾崑为何能同时拿下高端与主流"
    assert clean_title_text("《覆盖全品类全价位！华为乾崑200万成绩单》") == "覆盖全品类全价位 华为乾崑200万成绩单"


def test_split_title_lines_single_and_double() -> None:
    assert split_title_lines("短标题") == ["短标题"]
    lines = split_title_lines("别把辅助驾驶当自动驾驶国庆出行两条红线")
    assert len(lines) == 2
    assert "".join(lines) == "别把辅助驾驶当自动驾驶国庆出行两条红线"


def test_title_layout_vertical_sizes() -> None:
    small = title_layout("长假跑长途", width=1080, height=1920)
    assert small["main_size"] == 120 and small["sub_size"] is None
    medium = title_layout("别把辅助驾驶当自动驾驶国庆出行两条红线", width=1080, height=1920)
    assert medium["main_size"] == 80 and medium["sub_size"] == 52
    assert len(medium["lines"]) == 2


def test_title_layout_horizontal_smaller() -> None:
    long_title = "两个第一 华为乾崑为何能同时拿下高端与主流"
    vertical = title_layout(long_title, width=1080, height=1920)
    horizontal = title_layout(long_title, width=1920, height=1080)
    assert horizontal["main_size"] < vertical["main_size"]

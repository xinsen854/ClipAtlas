"""Deterministic script-to-visual-requirement parsing for the first recall pass."""

from __future__ import annotations

import re
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from clipatlas.domain.visual_protocol import ScriptVisualRequirement


_SENTENCE_END = re.compile(r"(?<=[\u3002\uff01\uff1f!?])")
_CLAUSE_SPLIT = re.compile(r"(?<=[\uff0c,\uff1b;])")
_TEMPORAL = {
    "随后": "after",
    "然后": "after",
    "最后": "last",
    "同时": "simultaneous",
    "从": "from",
    "到": "to",
}
_ACTIONS = (
    "行驶", "行駛", "爬坡", "爬上", "下坡", "进入",
    "驶出", "通过", "涉水", "扭转", "停车",
    "加速", "制动", "展示", "旋转", "起飞",
)
_SCENES = (
    "沙砾路", "碎石路", "非铺装路", "山路", "盘山路",
    "泥地", "泥泞坡地", "陡坡", "城市道路",
    "室内", "室外", "海边", "港口", "贵州盘山路",
)
_SUBJECTS = (
    "泰钽700", "坦克700", "Tank 700", "BJ40", "BJ30",
    "北京越野", "车辆", "汽车", "无人机",
)
_OBJECTS = (
    "无人机", "大梁", "差速锁", "三把锁", "车轮", "轮胎", "座椅", "中控屏",
    "帐篷", "行李架", "绞盘", "手机", "话筒", "麦克风",
)
_CONFIGURATIONS = (
    "增程", "ADS", "NOA", "大梁", "差速锁", "三把锁", "四驱", "激光雷达",
)
_SCENE_ALTERNATIVES = {
    "沙砾路": ["碎石路", "非铺装路", "山路"],
    "碎石路": ["沙砾路", "非铺装路", "山路"],
    "非铺装路": ["沙砾路", "碎石路", "山路"],
    "泥地": ["泥泞坡地", "非铺装路"],
    "盘山路": ["山路", "山区道路", "蜿蜒山路"],
    "贵州盘山路": ["贵州", "盘山路", "山路"],
}
_QUANTITY = re.compile(
    r"\d+(?:\.\d+)?\s*(?:%|％|万|亿|公里|千米|米|秒|分钟|小时|年|台|辆|人|家|款|场)"
)


class RequirementDraft(BaseModel):
    """Semantic fields returned by Director; source coordinates stay local.

    The fields mirror the permanent video timeline axes.  API output therefore
    does not need a second translation layer before local retrieval.
    """

    model_config = ConfigDict(extra="forbid")

    source_quote: str = Field(min_length=1)
    subject: str | None = None
    action: str | None = None
    scene: str | None = None
    environment: str | None = None
    objects: list[str] = Field(default_factory=list)
    configurations: list[str] = Field(default_factory=list)
    quantities: list[str] = Field(default_factory=list)
    relations: list[str] = Field(default_factory=list)
    state_changes: list[str] = Field(default_factory=list)
    temporal_relation: str | None = None
    same_subject_required: bool = False
    continuous_action_required: bool = False
    simultaneous_required: bool = False
    accepted_expressions: list[str] = Field(default_factory=list)
    proof_expressions: list[str] = Field(default_factory=list)
    related_expressions: list[str] = Field(default_factory=list)
    generic_expressions: list[str] = Field(default_factory=list)
    must_have: list[str] = Field(default_factory=list)
    preferred: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    anchor_phrase: str | None = None
    importance: Literal["S", "A", "B"] = "A"
    candidate_scope: Literal[
        "same_video_preferred", "same_entity_required", "continuous_window_preferred",
        "separate_shots_allowed",
    ] = "continuous_window_preferred"


def materialize_requirements(
    script_text: str,
    drafts: list[RequirementDraft],
) -> list[ScriptVisualRequirement]:
    """Bind API semantics to exact, locally verified source ranges."""
    source_hash = sha256(script_text.encode("utf-8")).hexdigest()
    cursor = 0
    results: list[ScriptVisualRequirement] = []
    sentence = 0
    for clause, draft in enumerate(drafts):
        start = script_text.find(draft.source_quote, cursor)
        if start < 0:
            start = script_text.find(draft.source_quote)
        if start < 0:
            continue
        end = start + len(draft.source_quote)
        # The API may point at a key phrase inside the exact quote.  Ignore an
        # invalid anchor instead of failing the whole script analysis.
        anchor_phrase = draft.anchor_phrase
        if anchor_phrase is not None and anchor_phrase not in draft.source_quote:
            anchor_phrase = None
        requirement_id = sha256(
            f"{source_hash}:{start}:{end}:{draft.source_quote}".encode("utf-8")
        ).hexdigest()[:24]
        payload = draft.model_dump()
        payload["anchor_phrase"] = anchor_phrase
        results.append(ScriptVisualRequirement(
            id=requirement_id,
            sentence_id=f"sentence-{sentence}",
            clause_id=f"sentence-{sentence}-clause-{clause}",
            source_text_hash=source_hash,
            source_char_start=start,
            source_char_end=end,
            origin="api",
            **payload,
        ))
        cursor = end
        if draft.source_quote.rstrip().endswith(tuple("。！？!?")):
            sentence += 1
    return results


def _clean_parts(text: str, pattern: re.Pattern[str]) -> list[tuple[str, int, int]]:
    result: list[tuple[str, int, int]] = []
    cursor = 0
    for match in pattern.finditer(text):
        end = match.end()
        value = text[cursor:end].strip()
        if value:
            start = text.find(value, cursor, end)
            result.append((value, start, start + len(value)))
        cursor = end
    tail = text[cursor:].strip()
    if tail:
        start = text.find(tail, cursor)
        result.append((tail, start, start + len(tail)))
    return result


def parse_script_visual_requirements(script_text: str) -> list[ScriptVisualRequirement]:
    """Split sentences and clauses while keeping exact source character ranges."""
    normalized = script_text.strip()
    if not normalized:
        return []
    source_offset = len(script_text) - len(script_text.lstrip())
    source_hash = sha256(script_text.encode("utf-8")).hexdigest()
    requirements: list[ScriptVisualRequirement] = []
    sentence_number = 0
    for sentence, sentence_start, sentence_end in _clean_parts(normalized, _SENTENCE_END):
        sentence_id = f"sentence-{sentence_number}"
        clauses = _clean_parts(sentence, _CLAUSE_SPLIT)
        if not clauses:
            clauses = [(sentence, sentence_start, sentence_end)]
        sentence_subject: str | None = None
        for clause_number, (quote, local_start, local_end) in enumerate(clauses):
            absolute_start = source_offset + sentence_start + max(0, local_start)
            absolute_end = source_offset + sentence_start + max(local_start + 1, local_end)
            explicit_subject = next((value for value in _SUBJECTS if value.casefold() in quote.casefold()), None)
            if explicit_subject is not None:
                sentence_subject = explicit_subject
            subject = explicit_subject or sentence_subject
            action = next((value for value in _ACTIONS if value in quote), None)
            # Prefer the most specific scene phrase. Otherwise "贵州盘山路"
            # would collapse to the earlier substring "山路" and lose exactly
            # the location detail needed for visual matching.
            scene = max((value for value in _SCENES if value in quote), key=len, default=None)
            objects = [value for value in _OBJECTS if value in quote]
            configurations = [value for value in _CONFIGURATIONS if value in quote]
            quantities = [re.sub(r"\s+", "", match.group(0)) for match in _QUANTITY.finditer(quote)]
            temporal_relation = next((value for key, value in _TEMPORAL.items() if key in quote), None)
            same_subject = sentence_subject is not None and (
                clause_number > 0
                or any(key in quote for key in ("同一", "同一辆", "同一辆车"))
            )
            action_values = [action] if action else []
            scene_values = [scene] if scene else []
            related = [
                *action_values,
                *scene_values,
                *_SCENE_ALTERNATIVES.get(scene or "", []),
                *objects,
                *configurations,
            ]
            must_have = list(dict.fromkeys(
                value for value in (subject, action, scene, *configurations) if value
            ))
            importance: Literal["S", "A", "B"] = "S" if subject and action else "A"
            requirement_id = sha256(
                f"{source_hash}:{absolute_start}:{absolute_end}:{quote}".encode("utf-8")
            ).hexdigest()[:24]
            requirements.append(ScriptVisualRequirement(
                id=requirement_id,
                sentence_id=sentence_id,
                clause_id=f"{sentence_id}-clause-{clause_number}",
                source_quote=quote,
                source_text_hash=source_hash,
                source_char_start=absolute_start,
                source_char_end=absolute_end,
                subject=subject,
                action=action,
                scene=scene,
                environment=scene,
                objects=objects,
                configurations=configurations,
                quantities=quantities,
                accepted_expressions=[quote],
                proof_expressions=[quote],
                related_expressions=list(dict.fromkeys(related)),
                must_have=must_have,
                temporal_relation=temporal_relation,
                same_subject_required=same_subject,
                continuous_action_required=temporal_relation == "after" and action is not None,
                simultaneous_required=temporal_relation == "simultaneous",
                anchor_phrase=quote if importance == "S" else None,
                importance=importance,
                candidate_scope=(
                    "same_entity_required" if same_subject else "continuous_window_preferred"
                ),
                origin="local_fallback",
            ))
        sentence_number += 1
    return requirements

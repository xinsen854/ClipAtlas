"""A whole-script retrieval plan; source text and timing remain caller-owned."""
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from clipatlas.providers.errors import ProviderRequestError
from clipatlas.roughcut.models import ScriptBeat


class ShotIntent(BaseModel):
    # AI 结构化输出偶会附带导演分级等附加字段（director_units / director_importance 等），
    # 忽略多余字段而不是让整条文案解析失败。
    model_config = ConfigDict(extra="ignore")
    start_sequence: int = Field(ge=0)
    end_sequence: int = Field(ge=0)
    subject: str = Field(min_length=1, max_length=300)
    purpose: str = Field(min_length=1, max_length=500)
    evidence: Literal["visual", "asr", "ocr"]
    match_type: Literal["direct", "supporting"]
    visual_queries: list[str] = Field(min_length=1, max_length=2)
    keywords: list[str] = Field(default_factory=list, max_length=3)
    alternatives: list[str] = Field(default_factory=list, max_length=2)
    supporting_queries: list[str] = Field(default_factory=list, max_length=2)

    @field_validator("visual_queries", "keywords", "alternatives", "supporting_queries")
    @classmethod
    def valid_queries(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or len(value) > 200 for value in values):
            raise ValueError("queries must be nonempty and concise")
        return list(dict.fromkeys(value.strip() for value in values))


class Storyboard(BaseModel):
    model_config = ConfigDict(extra="ignore")
    shots: list[ShotIntent] = Field(min_length=1, max_length=40)


def parse_storyboard(content: str) -> Storyboard:
    text = content.strip()
    if text.startswith("```") and text.endswith("```"):
        text = "\n".join(text.splitlines()[1:-1])
    decoded = json.loads(text)
    if isinstance(decoded, list):
        if len(decoded) == 1 and isinstance(decoded[0], dict) and "shots" in decoded[0]:
            decoded = decoded[0]
        elif decoded and all(isinstance(item, dict) and "start_sequence" in item for item in decoded):
            decoded = {"shots": decoded}
    return Storyboard.model_validate(decoded)


def apply_storyboard(beats: list[ScriptBeat], storyboard: Storyboard) -> list[ScriptBeat]:
    cursor = 0
    planned: list[ScriptBeat] = []
    for shot in storyboard.shots:
        if shot.start_sequence != cursor or not cursor <= shot.end_sequence < len(beats):
            raise ProviderRequestError("全文选材规划必须按顺序覆盖每个文案单元，不能漏句或重排")
        group = beats[cursor:shot.end_sequence + 1]
        # Length is a pacing preference, not an integrity failure: split only at the
        # original timed boundaries if the model grouped too much related content.
        groups: list[list[ScriptBeat]] = []
        for beat in group:
            if not groups or beat.timeline_end_ms - groups[-1][0].timeline_start_ms > 16000:
                groups.append([beat])
            else:
                groups[-1].append(beat)
        section_cursor = cursor
        for section in groups:
            text = " ".join(beat.text for beat in section)
            planned.append(section[0].model_copy(update={
                "sequence": len(planned), "text": text, "query_text": text,
                "timeline_end_ms": section[-1].timeline_end_ms,
                "target_duration_ms": section[-1].timeline_end_ms - section[0].timeline_start_ms,
                "retrieval_intent": shot.model_copy(update={"start_sequence": section_cursor,
                    "end_sequence": section_cursor + len(section) - 1}).model_dump(mode="json"),
            }))
            section_cursor += len(section)
        cursor = shot.end_sequence + 1
    if cursor != len(beats):
        raise ProviderRequestError("全文选材规划未覆盖全部文案")
    return planned


STORYBOARD_PROMPT = """Plan footage retrieval for a complete narrated edit. Return ONE JSON object
with a shots array, following the supplied schema. This is a generic editing task, not a keyword
to file mapping. You have no source filenames and must not invent any source timestamps.
Each input unit has an immutable sequence, text and duration_ms. Cover all unit sequences exactly
once in order using start_sequence/end_sequence. Group adjacent sentences ONLY when they describe
the same subject and visual idea. Prefer content windows of about 5-12 seconds; combined windows
must not exceed 16 seconds. Keep distinct demonstrations and topic changes separate. Do not split
one input unit. A source sentence may already be long: leave it as its own window.
For each window specify subject (resolved from full context), purpose (what the viewer should
understand), evidence (visual/asr/ocr), match_type (direct/supporting), 1-2 concise visual_queries,
up to 3 short keywords, up to 2 acceptable alternative visual_queries, and 1-2 supporting_queries.
The user has a fixed footage library. Supporting_queries are a broader same-subject fallback:
ordinary use, the surrounding scene, subject presentation or experience when precise details are
absent. Do not require a specific invisible feature in supporting_queries. These illustrate the
narration but are NOT evidence of its technical claims. Never invent or change the subject.
Use visual for physical actions, products, places and features. Use asr for actual spoken quotes
or interview content. Use ocr for visible names, labels, displays or figures. Keywords must be
short literal source phrases suitable for substring search, not whole sentences. ASR/OCR matches
are recall evidence, not proof of what the frame depicts. Never substitute a different entity.
Direct: concrete facts, actions or features need their actual visible subject/demonstration.
Do not invent a filmed stress test from a numerical claim; clear diagrams can illustrate structure.
Supporting: abstract rhetoric, transitions, broad evaluation or positioning can use ordinary related
scenes, subject beauty shots, relevant events or usage. A figurative flag is not a literal flag.
Do not require a specific person or place to appear in illustrative B-roll unless that is the point.
For direct windows, alternatives may broaden camera distance or wording, never change the object
or turn a specific feature into unrelated generic imagery. Supporting alternatives must retain
subject/category/context. Do not require impossible internal or invisible capabilities to be visible.
Project semantic hints are conditional preferences, not blanket orders overriding the current unit.
Write queries and purpose in the source language. Do not add 'close-up' to every query. Prefer
watchable continuous action and stable views; sentence punctuation does not require an edit cut.
"""

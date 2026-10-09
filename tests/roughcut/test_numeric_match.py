"""Numeric-claim matching: 200W/200万、86%、12个月 等数字尽量与画面 OCR/ASR 对上。"""
from uuid import uuid4

from clipatlas.domain.models import SemanticAnnotation
from clipatlas.roughcut.models import PlannerSettings, ScriptBeat
from clipatlas.roughcut.scoring import CandidateScorer, extract_number_tokens


def test_extract_number_tokens_normalizes_units() -> None:
    assert "200万" in extract_number_tokens("拥有200W用户规模")
    assert "200万" in extract_number_tokens("超过200万用户")
    assert "86%" in extract_number_tokens("高强度钢占比86%")
    assert "12个月" in extract_number_tokens("从44个月缩到12个月")
    assert "5.27倍" in extract_number_tokens("安全系数达5.27倍")


def test_numeric_score_boosts_matching_frames() -> None:
    beat = _beat("拥有200万用户规模，占比86%", importance="S")
    hit = _Hit(ocr_texts=["华为乾崑 200万用户 规模占比 86%"])
    score = CandidateScorer(PlannerSettings()).score(beat, hit, needed_duration_ms=4000)
    assert score.numeric_score > 0.99
    # 数字命中加成后总分明显高于无数字命中的同类画面（约 0.44）。
    assert score.total_score > 0.5


def test_numeric_score_zero_without_numbers() -> None:
    beat = _beat("这个车开起来很稳")
    score = CandidateScorer(PlannerSettings()).score(beat, _Hit([]), needed_duration_ms=4000)
    assert score.numeric_score == 0.0


def _beat(text: str, importance: str | None = None) -> ScriptBeat:
    intent = {"director_importance": importance} if importance else {}
    return ScriptBeat(
        id=uuid4(), project_id=uuid4(), narration_track_id=uuid4(),
        sequence=0, text=text, timeline_start_ms=0,
        timeline_end_ms=4000, target_duration_ms=4000, query_text=text,
        retrieval_intent=intent,
    )


class _Hit:
    def __init__(self, ocr_texts: list[str]):
        self.segment_id = uuid4()
        self.video_id = uuid4()
        self.source_uri = "file:///x.mp4"
        self.source_start_ms = 0
        self.source_end_ms = 4000
        self.score = 0.5
        self.asr_texts: list[str] = []
        self.ocr_texts = ocr_texts
        self.annotation = SemanticAnnotation(
            segment_id=self.segment_id, origin="ai", description="车辆画面",
            objects=[], actions=[], scene=[], characters=[], ocr=[],
        )

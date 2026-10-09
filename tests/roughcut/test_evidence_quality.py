from types import SimpleNamespace
from uuid import uuid4

import pytest

from clipatlas.api.routes.search import _scoped_video_ids
from clipatlas.director.local_fit import fit
from clipatlas.director.models import DirectorUnit
from clipatlas.domain.evidence import ClaimMatch
from clipatlas.domain.models import AnnotationOrigin, ObjectiveFact, SemanticAnnotation
from clipatlas.retrieval.local_rough_cut import LocalRoughCutHit
from clipatlas.roughcut.evidence import finalize_evidence
from clipatlas.roughcut.models import RoughCutPlan, ScriptBeat
from clipatlas.roughcut.planner import RoughCutPlanner
from clipatlas.roughcut.quality import build_quality_report


def _unit(**updates):
    values = dict(text_range="泰钽700在泥泞山坡行驶", importance="S", topic="越野",
                  required_objects=["泰钽700"], must_have=["泰钽700在泥泞山坡行驶"])
    return DirectorUnit(**(values | updates))


def _annotation(**updates):
    return SemanticAnnotation(**(dict(segment_id=uuid4(), origin=AnnotationOrigin.AI,
                                      description="素材", objects=["泰钽700"]) | updates))


def _beat(duration=10000):
    return ScriptBeat(project_id=uuid4(), narration_track_id=uuid4(), sequence=0,
                      text="完整句", query_text="完整句", timeline_start_ms=0,
                      timeline_end_ms=duration, target_duration_ms=duration)


def _hit(**updates):
    annotation = _annotation()
    return LocalRoughCutHit(**(dict(
        segment_id=annotation.segment_id, video_id=uuid4(), source_uri="file:///a.mp4",
        source_start_ms=0, source_end_ms=6000, annotation=annotation, score=0.9,
        filename="a.mp4", hybrid_score=0.9,
        anchor_start_ms=5500, anchor_end_ms=6000, schedule_level="exact",
    ) | updates))


def _planner():
    return RoughCutPlanner(narration_store=None, search=None, store=None)


def test_static_target_cannot_prove_driving_on_muddy_slope():
    verdict = fit(_unit(), _annotation(actions=["静止展示"]))
    assert verdict.level == "SUPPORT"
    assert verdict.missing_must_have == ["泰钽700在泥泞山坡行驶"]


@pytest.mark.parametrize("avoid", ["非泰钽700的其他车型", "禁止非泰钽700车型"])
def test_avoiding_other_models_does_not_reject_target(avoid):
    unit = _unit(must_have=["泰钽700"], avoid=[avoid])
    assert fit(unit, _annotation()).level == "DIRECT"


@pytest.mark.parametrize("evidence", ["非泰钽700", "不是泰钽700", "泰钽7000"])
def test_negative_and_different_model_annotations_do_not_prove_target(evidence):
    assert fit(_unit(must_have=["泰钽700"]), _annotation(objects=[evidence])).level != "DIRECT"


def test_must_have_cannot_override_missing_typed_action():
    verdict = fit(_unit(must_have=["泰钽700"], required_actions=["行驶"]),
                  _annotation(actions=["静止展示"]))
    assert verdict.level == "SUPPORT"


def test_more_specific_action_requires_its_qualifier():
    unit = _unit(must_have=[], required_actions=["承受坑洼扭转"])
    assert fit(unit, _annotation(actions=["承受扭转"])).level == "SUPPORT"


def test_bilingual_aliases_are_shared_by_fit():
    unit = _unit(must_have=[], required_objects=["华为"])
    assert fit(unit, _annotation(objects=["Huawei"])).level == "DIRECT"


def test_explicit_video_scope_is_intersected_with_project():
    own, foreign = uuid4(), uuid4()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        library_catalog=SimpleNamespace(list_video_ids_for_project=lambda _: [own]))))
    assert _scoped_video_ids(request, uuid4(), [foreign, own, own]) == [own]
    assert _scoped_video_ids(request, uuid4(), [foreign]) == []


def test_missing_scope_resolver_fails_closed():
    from clipatlas.roughcut.errors import RoughCutConfigurationError
    with pytest.raises(RoughCutConfigurationError):
        _planner()._resolve_project_video_scope(uuid4())


def test_five_second_cuts_keep_evidence_at_end_of_six_second_candidates():
    clips, _ = _planner()._fill_beat(_beat(), [_hit(), _hit()], {}, None)
    assert len(clips) == 2
    for clip in clips:
        assert (clip.source_in_ms, clip.source_out_ms) == (1000, 6000)
        assert clip.evidence_retained is True


def test_anchor_too_long_for_cut_downgrades_exact():
    clips, _ = _planner()._fill_beat(_beat(3000), [
        _hit(anchor_start_ms=0, anchor_end_ms=6000),
    ], {}, None)
    assert clips[0].schedule_level == "source"
    assert clips[0].evidence_retained is False


def test_final_window_outside_safe_range_is_not_exact():
    hit = _hit(safe_start_ms=1000, safe_end_ms=6000)
    clips, _ = _planner()._fill_beat(_beat(6000), [hit], {}, None)
    assert clips[0].schedule_level == "source"
    assert "safe range" in clips[0].evidence_check_reasons[0]


def test_readable_two_second_candidate_reuses_instead_of_reporting_corruption():
    clips, _ = _planner()._fill_beat(
        _beat(6000), [_hit(source_end_ms=2000, anchor_start_ms=0, anchor_end_ms=2000)], {}, None,
    )
    assert clips[-1].timeline_out_ms == 6000
    assert any(clip.schedule_level == "reuse" for clip in clips)


def test_fact_outside_final_cut_cannot_prove_direct():
    annotation = _annotation(facts=[ObjectiveFact(
        layer="event", value="泰钽700在泥泞山坡行驶", start_ms=0, end_ms=500,
    )])
    hit = _hit(annotation=annotation)
    clips, _ = _planner()._fill_beat(_beat(), [hit, _hit()], {}, None)
    clip = next(c for c in clips if c.video_id == hit.video_id)
    checked = finalize_evidence(clip, hit, [_unit()])
    assert checked.director_fit == "SUPPORT"
    assert checked.schedule_level == "related"


def test_all_director_units_are_checked_after_trimming():
    hit = _hit()
    clips, _ = _planner()._fill_beat(_beat(6000), [hit], {}, None)
    checked = finalize_evidence(clips[0], hit, [
        _unit(must_have=["泰钽700"]), _unit(must_have=["行驶"]),
    ])
    assert checked.director_fit == "SUPPORT"
    assert "行驶" in checked.director_missing_requirements


def test_quality_report_counts_union_overlap_without_claiming_human_accuracy():
    beat = _beat(6000)
    clips, _ = _planner()._fill_beat(beat, [_hit()], {}, None)
    first = clips[0].model_copy(update={"source_in_ms": 0, "source_out_ms": 3000,
                                       "timeline_out_ms": 3000})
    second = first.model_copy(update={"source_in_ms": 2000, "source_out_ms": 5000,
                                      "timeline_in_ms": 3000, "timeline_out_ms": 6000})
    report = build_quality_report([first, second], [beat], 6000, {
        str(first.video_id): [(0, 2000, 0), (1000, 2500, 1)],
    })
    assert report.timeline_coverage == 1
    assert report.repeated_source_ms == 1000
    assert report.batch_repeated_source_ms == 3000
    assert report.beats[0].clip_count == 2
    assert report.one_shot_beat_ratio == 0
    assert report.human_s_accuracy is None
    assert report.human_effective_accuracy is None
    assert report.accuracy_targets_verified is False
    assert report.pollution_counts == {"unknown": 2}


def test_quality_report_survives_plan_serialization_and_old_plans_remain_unknown():
    beat = _beat(6000)
    clips, _ = _planner()._fill_beat(beat, [_hit()], {}, None)
    report = build_quality_report(clips, [beat], 6000)
    plan = RoughCutPlan(project_id=beat.project_id, narration_track_id=beat.narration_track_id,
                        narration_revision=1, revision=1, total_duration_ms=6000,
                        settings={}, beats=[beat], clips=clips, quality_report=report)
    assert RoughCutPlan.model_validate_json(plan.model_dump_json()).quality_report == report
    old = plan.model_dump(exclude={"quality_report"})
    assert RoughCutPlan.model_validate(old).quality_report is None


def test_quality_report_counts_each_claim_once_at_its_best_level():
    beat = _beat(6000)
    clips, _ = _planner()._fill_beat(beat, [_hit()], {}, None)
    direct = ClaimMatch(claim_id="model", source_quote="BJ40", importance="S",
                        goal="proof", level="DIRECT")
    unknown = direct.model_copy(update={"level": "UNKNOWN"})
    related = ClaimMatch(claim_id="lifestyle", source_quote="山野生活", importance="A",
                         goal="related", level="SUPPORT")
    first = clips[0].model_copy(update={"claim_matches": [unknown, related]})
    second = clips[0].model_copy(update={"claim_matches": [direct], "timeline_in_ms": 3000,
        "timeline_out_ms": 6000, "source_in_ms": 0, "source_out_ms": 3000})
    first = first.model_copy(update={"timeline_out_ms": 3000, "source_out_ms": 3000})
    report = build_quality_report([first, second], [beat], 6000)
    assert report.claim_counts == {"DIRECT": 1, "SUPPORT": 1}
    assert report.auto_s_claim_direct_ratio == 1
    assert report.auto_effective_claim_ratio == 1

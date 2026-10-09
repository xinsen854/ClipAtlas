from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from clipatlas.director.analyzer import DirectorAnalyzer
from clipatlas.director.claim_matching import evidence_records, match_claim
from clipatlas.director.contract import validate_unit_claims
from clipatlas.director.local_fit import fit
from clipatlas.director.models import DirectorUnit
from clipatlas.director.models import DirectorAnalysis
from clipatlas.director.service import DirectorService
from clipatlas.director.store import DirectorCacheStore
from clipatlas.domain.evidence import EvidenceAlternative, EvidenceStatement, Proposition, VisualClaim
from clipatlas.domain.models import ObjectiveFact, SemanticAnnotation
from clipatlas.providers.contracts import AnalyzeSegmentRequest
from clipatlas.providers.evidence_contract import validate_facts
from clipatlas.providers.errors import ProviderStructuredOutputError


def proposition(predicate="identity", value="BJ40", subject="BJ40", **kwargs):
    return Proposition(subject=subject, predicate=predicate, value=value, **kwargs)


def fact(p=None, *, entity="car_1", kind="visual", start=1000, end=2000, **updates):
    return ObjectiveFact(layer="subject", value="观察", start_ms=start, end_ms=end,
        statement=EvidenceStatement(proposition=p or proposition(), entity_id=entity, kind=kind,
            representation="real_scene" if kind == "visual" else "screen",
            frame_ids=["frame_0", "frame_1"], temporal_basis="interval", **updates))


def claim(p=None, *, quote="BJ40", kinds=None, conditions=None, simultaneous=False):
    return VisualClaim(claim_id=quote, source_quote=quote, any_of=[EvidenceAlternative(
        all_of=conditions or [p or proposition()], allowed_kinds=kinds or ["visual"],
        simultaneous=simultaneous)])


def annotation(facts=None, **updates):
    return SemanticAnnotation(segment_id=uuid4(), origin="ai", description="观察",
                              facts=facts or [], **updates)


def test_partial_equipment_does_not_erase_model_evidence():
    model = claim()
    equipment = claim(proposition("configuration", "车载无人机"), quote="车载无人机")
    unit = DirectorUnit(text_range="BJ40配备车载无人机", importance="S", topic="配置",
                        claims=[model, equipment])
    verdict = fit(unit, annotation([fact()]))
    assert verdict.level == "SUPPORT"
    assert [m.level for m in verdict.claim_matches] == ["DIRECT", "SUPPORT"]
    assert verdict.claim_matches[0].evidence_ids
    assert verdict.claim_matches[1].missing_conditions


def test_presence_does_not_prove_operation_and_ocr_cannot_prove_action():
    action = claim(proposition("action", "起飞", "无人机"), quote="无人机起飞")
    records = evidence_records(annotation([
        fact(proposition("presence", "无人机", "无人机")),
        fact(proposition("action", "起飞", "无人机"), kind="source_text"),
    ]))
    assert match_claim(action, "S", records).level != "DIRECT"


def test_aerial_camera_does_not_become_drone_object():
    a = annotation(objects=["SUV"], scene=["aerial drone footage"], camera_motion="drone hover")
    assert match_claim(claim(proposition("identity", "无人机", "无人机")),
                       "S", evidence_records(a)).level == "UNKNOWN"


def test_conditions_cannot_bind_different_vehicles():
    driving = proposition("action", "行驶")
    request = claim(conditions=[proposition(), driving])
    records = evidence_records(annotation([fact(entity="car_1"), fact(driving, entity="car_2")]))
    result = match_claim(request, "S", records)
    assert result.level == "SUPPORT"
    assert "bind" in result.reasons[0]


def test_simultaneous_relation_cannot_join_disjoint_time_ranges():
    request = claim(conditions=[proposition(), proposition("configuration", "车载无人机")],
                    simultaneous=True)
    records = evidence_records(annotation([fact(),
        fact(proposition("configuration", "车载无人机"), start=2000, end=3000)]))
    assert match_claim(request, "S", records).level != "DIRECT"


def test_quantity_requires_unit_and_semantic_scope():
    with pytest.raises(ValidationError):
        proposition("quantity", "1500")
    request = claim(proposition("quantity", "1500", unit="场/年", scope="线下活动"))
    records = evidence_records(annotation([
        fact(proposition("quantity", "1500", unit="米", scope="垂直落差")),
    ]))
    assert match_claim(request, "S", records).level != "DIRECT"


def test_frame_point_is_kept_but_end_boundary_is_excluded():
    f = ObjectiveFact(layer="subject", value="BJ40", start_ms=1500, end_ms=1500,
        statement=EvidenceStatement(proposition=proposition(), entity_id="car_1", kind="visual",
            representation="real_scene", frame_ids=["frame_0"], temporal_basis="point"))
    a = annotation([f])
    assert match_claim(claim(), "S", evidence_records(a, source_window=(1000, 2000))).level == "DIRECT"
    assert match_claim(claim(), "S", evidence_records(a, source_window=(1000, 1500))).level == "UNKNOWN"


def test_alternative_evidence_is_or_not_and():
    request = claim(proposition("configuration", "三把锁"))
    request.any_of.append(EvidenceAlternative(all_of=[proposition("configuration", "三把锁")],
                                              allowed_kinds=["source_text"]))
    records = evidence_records(annotation([fact(proposition("configuration", "三把锁"),kind="source_text")]))
    assert match_claim(request, "S", records).level == "DIRECT"


def test_explicit_negation_blocks_direct():
    request = claim()
    records = evidence_records(annotation([fact(proposition(polarity="negative"))]))
    assert match_claim(request, "S", records).level == "REJECT"


def test_legacy_model_ocr_is_usable_but_not_other_model_or_variant():
    a = annotation(ocr=["北京 BJ40 增程"])
    assert match_claim(claim(kinds=["source_text"]), "S", evidence_records(a)).level == "DIRECT"
    variant = claim(proposition(value="BJ40增程悦野飞行版",subject="BJ40增程悦野飞行版"),kinds=["source_text"])
    assert match_claim(variant, "S", evidence_records(a)).level != "DIRECT"
    wrong = annotation(ocr=["坦克700"])
    target = claim(proposition(value="泰钽700",subject="泰钽700"), kinds=["source_text"])
    assert match_claim(target, "S", evidence_records(wrong)).level == "UNKNOWN"


def test_hallucinated_action_is_not_dropped_to_create_false_direct():
    unit = DirectorUnit(text_range="BJ40配备无人机",importance="S",topic="配置",claims=[
        claim(), claim(proposition("action", "起飞", "无人机"),quote="无人机"),
    ])
    checked = validate_unit_claims(unit, unit.text_range)
    result = fit(checked, annotation([fact()]))
    assert result.claim_matches[0].level == "DIRECT"
    assert result.claim_matches[1].level == "UNKNOWN"
    assert result.level == "SUPPORT"


def test_timed_ingest_fact_must_reference_real_input_frame_times():
    request = AnalyzeSegmentRequest(video_id=uuid4(),segment_id=uuid4(),start_ms=0,end_ms=3000,
        source_uri="file:///a.mp4",frame_uris=["file:///a.jpg","file:///b.jpg"],
        frame_timestamps_ms=[1000,2000])
    assert validate_facts([fact()],request)
    with pytest.raises(ProviderStructuredOutputError):
        validate_facts([fact(start=500)],request)


def test_same_ocr_block_can_bind_model_to_configuration_but_separate_blocks_cannot():
    request = claim(conditions=[
        proposition(), proposition("configuration", "增程"),
    ], kinds=["source_text"])
    together = evidence_records(annotation(ocr=["北京 BJ40 增程"]));
    separate = evidence_records(annotation(ocr=["BJ40", "增程"]));
    assert match_claim(request, "S", together).level == "DIRECT"
    assert match_claim(request, "S", separate).level != "DIRECT"


@pytest.mark.asyncio
async def test_actual_project_rules_sent_once_and_cached(tmp_path):
    requests=[]
    unit=DirectorUnit(text_range="BJ40",importance="S",topic="车型",claims=[claim()],visual_goal="proof")
    async def handler(request):
        import json
        requests.append(json.loads(request.content))
        return httpx.Response(200,json={"choices":[{"message":{"content":json.dumps(
            {"units":[unit.model_dump(mode="json")]},ensure_ascii=False)}}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        analyzer=DirectorAnalyzer(api_key="test",base_url="https://test.invalid",client=client)
        service=DirectorService(analyzer,DirectorCacheStore(tmp_path/'director.db'))
        first=await service.analyze_cached("BJ40",rules_revision="project:rules-v1",rules_text="禁止错车型")
        second=await service.analyze_cached("BJ40",rules_revision="project:rules-v1",rules_text="禁止错车型")
    assert first==second
    assert len(requests)==1
    assert "禁止错车型" in requests[0]["messages"][1]["content"]
    assert not first.units[0].contract_issues


@pytest.mark.asyncio
async def test_failed_v4_analysis_uses_old_cache_only_as_declared_fallback(tmp_path):
    class FailingAnalyzer:
        def _empty_analysis(self, text, revision):
            return DirectorAnalysis(script_text=text, script_hash="hash", prompt_version="v4",
                                    rules_revision=revision, units=[])
        async def analyze(self, text, rules_revision=None, *, rules_text=""):
            raise RuntimeError("offline")
    store = DirectorCacheStore(tmp_path / "director.db")
    old = DirectorAnalysis(script_text="BJ40", script_hash="hash", prompt_version="v3",
                           rules_revision="r1", units=[])
    store.put(old)
    result = await DirectorService(FailingAnalyzer(), store).analyze_cached(
        "BJ40", rules_revision="r1", rules_text="rule text",
    )
    assert result.prompt_version == "v3"
    assert "旧版缓存" in result.contract_issues[0]

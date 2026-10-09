import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from clipatlas.director.analyzer import DirectorAnalyzer
from clipatlas.director.local_fit import fit
from clipatlas.director.models import DirectorUnit
from clipatlas.director.service import analyze_director_units
from clipatlas.director.store import DirectorCacheStore
from clipatlas.domain.models import AnnotationOrigin, SemanticAnnotation
from clipatlas.providers.errors import ProviderAuthenticationError, ProviderRateLimitError

_SCRIPT = "第一道是性能。这个车是带大梁的。遇到大坑拧的是大梁不是车身。这件事的意义正在这里。"


def _units_payload() -> dict[str, object]:
    return {
        "units": [
            {
                "text_range": "第一道是性能。这个车是带大梁的。遇到大坑拧的是大梁不是车身。",
                "importance": "S",
                "topic": "越野性能",
                "subtopics": ["大梁结构"],
                "required_subjects": ["泰钽700"],
                "required_objects": ["大梁"],
                "required_actions": ["承受坑洼扭转"],
                "acceptable_surrogates": ["底盘大梁结构图"],
                "avoid": ["电池骨架"],
                "visual_function": "证明车辆大梁结构和承受冲击能力",
                "anchor_phrase": "遇到大坑拧的是大梁不是车身",
            },
            {
                "text_range": "这件事的意义正在这里。",
                "importance": "B",
                "topic": "转折强调",
                "required_subjects": [],
                "required_objects": [],
                "required_actions": [],
                "acceptable_surrogates": [],
                "avoid": [],
                "visual_function": "连接前文",
                "anchor_phrase": "",
            },
        ],
        "requirements": [
            {
                "source_quote": "这个车是带大梁的。",
                "subject": "泰钽700",
                "action": None,
                "scene": None,
                "objects": ["大梁"],
                "configurations": ["大梁"],
                "quantities": [],
                "relations": [],
                "state_changes": [],
                "temporal_relation": None,
                "same_subject_required": False,
                "continuous_action_required": False,
                "simultaneous_required": False,
                "accepted_expressions": ["泰钽700带大梁"],
                "proof_expressions": ["泰钽700大梁结构"],
                "related_expressions": ["越野车底盘"],
                "generic_expressions": ["车辆底盘"],
                "must_have": ["泰钽700", "大梁"],
                "preferred": ["大梁实拍"],
                "avoid": ["电池骨架"],
                "importance": "S",
                "candidate_scope": "continuous_window_preferred",
            }
        ],
    }


def _success_response() -> dict[str, object]:
    return {"choices": [{"message": {"content": json.dumps(_units_payload(), ensure_ascii=False)}}]}


def _analyzer(transport: httpx.AsyncBaseTransport) -> DirectorAnalyzer:
    return DirectorAnalyzer(
        api_key="fixture",
        base_url="https://example.test/v1",
        client=httpx.AsyncClient(transport=transport),
    )


def _annotation(description: str, *, characters=None, objects=None, actions=None) -> SemanticAnnotation:
    return SemanticAnnotation(
        segment_id=uuid4(),
        origin=AnnotationOrigin.AI,
        provider="fixture",
        description=description,
        characters=characters or [],
        objects=objects or [],
        actions=actions or [],
    )


@pytest.mark.asyncio
async def test_analyzer_parses_units_in_order() -> None:
    calls: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=_success_response())

    analysis = await _analyzer(httpx.MockTransport(handler)).analyze(_SCRIPT)

    assert analysis.script_hash
    assert [unit.importance for unit in analysis.units] == ["S", "B"]
    s_unit = analysis.units[0]
    assert s_unit.required_objects == ["大梁"]
    assert s_unit.anchor_phrase == "遇到大坑拧的是大梁不是车身"
    assert analysis.units_by_importance("S") == [s_unit]
    assert analysis.requirements[0].origin == "api"
    assert analysis.requirements[0].source_quote == "这个车是带大梁的。"
    assert analysis.requirements[0].configurations == ["大梁"]
    response_format = calls[0]["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    assert response_format["json_schema"]["schema"]["properties"]["units"]
    assert response_format["json_schema"]["schema"]["properties"]["requirements"]
    assert response_format["json_schema"]["schema"]["additionalProperties"] is False
    assert "Finished narration script" in calls[0]["messages"][1]["content"]


@pytest.mark.asyncio
async def test_analyzer_skips_api_for_blank_script() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("blank script must not call the API")

    analysis = await _analyzer(httpx.MockTransport(handler)).analyze("   ")

    assert analysis.units == []
    assert analysis.script_hash


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected"),
    [(401, ProviderAuthenticationError), (429, ProviderRateLimitError)],
)
async def test_analyzer_maps_upstream_errors(status: int, expected: type[Exception]) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": "nope"}})

    with pytest.raises(expected):
        await _analyzer(httpx.MockTransport(handler)).analyze(_SCRIPT)


def test_store_caches_and_reuses_by_full_key(tmp_path: Path) -> None:
    store = DirectorCacheStore(tmp_path / "director.db")
    analysis = DirectorAnalyzer(
        api_key="fixture", base_url="https://example.test/v1"
    )._empty_analysis(_SCRIPT)

    assert store.get(analysis) is None
    store.put(analysis)
    restored = store.get(analysis)
    assert restored is not None
    assert restored.script_hash == analysis.script_hash

    other = analysis.model_copy(update={"prompt_version": "director-v2"})
    assert store.get(other) is None
    assert store.count() == 1


@pytest.mark.asyncio
async def test_service_uses_cache_and_never_calls_api_again(tmp_path: Path) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_success_response())

    analyzer = _analyzer(httpx.MockTransport(handler))
    store = DirectorCacheStore(tmp_path / "director.db")

    first = await analyze_director_units(analyzer, store, _SCRIPT)
    second = await analyze_director_units(analyzer, store, _SCRIPT)

    assert first.script_hash == second.script_hash
    assert len(first.units) == 2
    assert calls == 1  # the second call was served from cache


def _s_unit() -> DirectorUnit:
    return DirectorUnit(
        text_range="性能段",
        importance="S",
        topic="越野性能",
        required_subjects=["泰钽700"],
        required_objects=["大梁"],
        required_actions=["承受坑洼扭转"],
        acceptable_surrogates=["底盘大梁结构图"],
        avoid=["电池骨架"],
        visual_function="证明大梁",
        anchor_phrase="遇到大坑拧的是大梁",
    )


def test_local_fit_direct_when_object_and_action_match() -> None:
    verdict = fit(_s_unit(), _annotation(
        "泰钽700压过交叉轴，大梁承受扭转",
        characters=["泰钽700"], objects=["大梁"], actions=["承受坑洼扭转"],
    ))
    assert verdict.level == "DIRECT"
    assert verdict.is_usable


def test_local_fit_support_when_only_substitute_matches() -> None:
    verdict = fit(_s_unit(), _annotation("底盘大梁结构示意图"))
    assert verdict.level == "SUPPORT"
    assert verdict.matched_surrogates == ["底盘大梁结构图"]


def test_local_fit_reject_takes_priority_over_direct() -> None:
    verdict = fit(_s_unit(), _annotation("越野车电池骨架特写", objects=["电池骨架"]))
    assert verdict.level == "REJECT"
    assert verdict.avoided_hits == ["电池骨架"]


def test_local_fit_unknown_without_annotation() -> None:
    verdict = fit(_s_unit(), None)
    assert verdict.level == "UNKNOWN"
    assert not verdict.is_usable


def test_local_fit_uses_ocr_and_facts_as_evidence() -> None:
    annotation = _annotation(
        "直播画面", objects=[], actions=[],
    ).model_copy(update={
        "ocr": ["央视新闻 正在直播 泰钽700"],
    })
    verdict = fit(_s_unit(), annotation)
    assert verdict.level == "SUPPORT"
    assert verdict.matched_subjects == ["泰钽700"]


def test_local_fit_unknown_when_nothing_matches() -> None:
    verdict = fit(_s_unit(), _annotation("主持人坐进驾驶室介绍座舱"))
    assert verdict.level == "UNKNOWN"
    assert verdict.reason


def test_local_fit_description_only_never_grants_direct() -> None:
    verdict = fit(
        _s_unit(),
        _annotation("旁白文字写着泰钽700的大梁正在承受坑洼扭转"),
    )
    assert verdict.level != "DIRECT"


def test_local_fit_requires_subject_when_director_requires_subject() -> None:
    verdict = fit(
        _s_unit(),
        _annotation("另一辆车的底盘", objects=["大梁"], actions=["承受坑洼扭转"]),
    )
    assert verdict.level == "SUPPORT"

    direct = fit(
        _s_unit(),
        _annotation(
            "泰钽700底盘",
            characters=["泰钽700"],
            objects=["大梁"],
            actions=["承受坑洼扭转"],
        ),
    )
    assert direct.level == "DIRECT"

from clipatlas.retrieval.local_rough_cut import split_keywords
from clipatlas.retrieval.text_normalization import (
    concepts_in_text,
    expand_search_terms,
    matched_terms,
    strong_match,
)


def test_bilingual_terms_match_without_ascii_substring_false_positive() -> None:
    terms = ["华为", "智驾", "新能源"]
    assert matched_terms("Huawei assisted driving system", terms) == ["华为", "智驾"]
    assert "新能源" not in matched_terms("several vehicles on a road", terms)


def test_keyword_priority_keeps_identity_and_rejects_bare_numbers() -> None:
    words = split_keywords("4月份华为乾崑智驾覆盖25家品牌，NOA渗透率34.2%")
    assert words[:3] == ["华为", "乾崑", "智驾"]
    assert "25家" in words and "34.2%" in words
    assert "4" not in words and "25" not in words


def test_exact_requires_query_specific_detail_when_available() -> None:
    query = ["华为", "乾崑", "智驾", "25家", "品牌"]
    assert not strong_match(["华为", "乾崑", "智驾"], query)
    assert strong_match(["华为", "智驾", "品牌"], query)


def test_automotive_and_scene_terms_expand_bidirectionally() -> None:
    query = "BJ40增程越野车在泥地爬坡，随后到海边露营"
    terms = split_keywords(query, include_ngram=False)
    expanded = expand_search_terms(terms, limit=48)

    assert {"BJ40", "增程", "越野车", "泥地", "爬坡", "海边", "露营"} <= set(terms)
    assert {"range extender", "off-road vehicle", "muddy", "hill climb", "coast", "camping"} <= set(expanded)
    assert {"越野", "行驶", "无人机"} <= set(
        concepts_in_text("off-road driving filmed from a drone view")
    )


def test_lidar_does_not_claim_generic_radar() -> None:
    assert matched_terms("vehicle has radar sensors", ["激光雷达"]) == []
    assert matched_terms("roof-mounted lidar sensor", ["激光雷达"]) == ["激光雷达"]


def test_expansion_keeps_all_canonical_facts_before_aliases() -> None:
    terms = ["北京越野", "BJ40", "增程", "无人机", "海边", "露营"]
    expanded = expand_search_terms(terms, limit=8)
    assert expanded[:6] == terms

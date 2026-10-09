from clipatlas.retrieval.text_normalization import expand_search_terms, matched_terms


def test_chinese_timeline_query_matches_legacy_english_annotation():
    query_terms = ["泰钽700", "贵州", "盘山路", "爬坡"]
    english = "Titan 700 climbs a winding mountain road in Guizhou over loose gravel."

    assert set(matched_terms(english, query_terms)) == set(query_terms)


def test_search_expansion_keeps_chinese_canonical_and_english_aliases():
    expanded = expand_search_terms(["贵州", "盘山路", "碎石路", "话筒"], limit=32)
    folded = {value.casefold() for value in expanded}

    assert "贵州" in expanded
    assert "guizhou" in folded
    assert "盘山路" in expanded
    assert any(value in expanded for value in ("winding mountain road", "mountain pass road"))
    assert "碎石路" in expanded
    assert "gravel road" in expanded
    assert "话筒" in expanded
    assert "microphone" in expanded

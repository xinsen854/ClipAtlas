from clipatlas.director.requirements import RequirementDraft, materialize_requirements


def test_invalid_api_anchor_phrase_is_dropped_instead_of_invented():
    script = "泰钽700在贵州盘山路向上爬。"
    draft = RequirementDraft(
        source_quote=script,
        subject="泰钽700",
        action="爬坡",
        scene="贵州盘山路",
        anchor_phrase="不存在的口播",
        importance="S",
    )

    requirement = materialize_requirements(script, [draft])[0]

    assert requirement.anchor_phrase is None


def test_valid_api_anchor_phrase_remains_exact_source_substring():
    script = "泰钽700在贵州盘山路向上爬。"
    draft = RequirementDraft(
        source_quote=script,
        subject="泰钽700",
        action="爬坡",
        scene="贵州盘山路",
        anchor_phrase="贵州盘山路",
        importance="S",
    )

    requirement = materialize_requirements(script, [draft])[0]

    assert requirement.anchor_phrase == "贵州盘山路"
    assert requirement.anchor_phrase in requirement.source_quote

from clipatlas.director.requirements import RequirementDraft, materialize_requirements, parse_script_visual_requirements


def test_api_requirement_uses_same_subject_action_scene_environment_axes():
    script = "泰钽700在贵州盘山路向上爬坡。"
    requirement = materialize_requirements(script, [RequirementDraft(
        source_quote=script,
        subject="泰钽700",
        action="爬坡",
        scene="贵州盘山路",
        environment="贵州盘山路",
        anchor_phrase="贵州盘山路向上爬坡",
        importance="S",
    )])[0]

    assert requirement.subject == "泰钽700"
    assert requirement.action == "爬坡"
    assert requirement.scene == "贵州盘山路"
    assert requirement.environment == "贵州盘山路"
    assert requirement.anchor_phrase == "贵州盘山路向上爬坡"


def test_invalid_api_anchor_is_dropped_without_losing_requirement():
    script = "泰钽700在贵州盘山路向上爬坡。"
    requirement = materialize_requirements(script, [RequirementDraft(
        source_quote=script,
        subject="泰钽700",
        action="爬坡",
        anchor_phrase="不存在于原文的词",
        importance="S",
    )])[0]

    assert requirement.anchor_phrase is None
    assert requirement.source_quote == script


def test_local_fallback_keeps_chinese_scene_as_environment_and_s_anchor():
    script = "泰钽700在贵州盘山路爬坡。"
    requirement = parse_script_visual_requirements(script)[0]

    assert requirement.subject == "泰钽700"
    assert requirement.action == "爬坡"
    assert requirement.scene == "贵州盘山路"
    assert requirement.environment == "贵州盘山路"
    assert requirement.anchor_phrase == requirement.source_quote
    assert requirement.importance == "S"

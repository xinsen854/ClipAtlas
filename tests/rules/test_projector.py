import importlib
from uuid import uuid4

import pytest


def _rules_module():
    try:
        return importlib.import_module("clipatlas.rules.models")
    except ModuleNotFoundError:
        pytest.fail("clipatlas.rules.models is not implemented yet")


def _projector_module():
    try:
        return importlib.import_module("clipatlas.rules.projector")
    except ModuleNotFoundError:
        pytest.fail("clipatlas.rules.projector is not implemented yet")


def _pack(*rules):
    models = _rules_module()
    return models.ProjectRulePack(
        project_id=uuid4(),
        revision=1,
        status=models.RulePackStatus.ACTIVE,
        rules=list(rules),
    )


def _rule(kind: str, *, match=None, replacement=None, hint=None, enabled=True):
    models = _rules_module()
    return models.ProjectRule(
        kind=models.RuleKind(kind),
        match=match,
        replacement=replacement,
        hint=hint,
        enabled=enabled,
    )


def _project(text: str, pack):
    projector = _projector_module().ProjectTextProjector()
    return projector.project(text, pack)


def test_projection_preserves_canonical_text_exactly() -> None:
    source = "  Model 700 enters public view.  "
    pack = _pack(
        _rule(
            "pronunciation",
            match="Model 700",
            replacement="Model seven hundred",
        )
    )

    result = _project(source, pack)

    assert result.canonical_text == source
    assert result.speech_text == "  Model seven hundred enters public view.  "
    assert result.subtitle_text == source


def test_speech_rules_do_not_change_subtitle_text() -> None:
    source = "Official Media presents Model 700 today."
    pack = _pack(
        _rule("speech_suppress", match="Official Media "),
        _rule("speech_replace", match="Model 700", replacement="Model seven hundred"),
    )

    result = _project(source, pack)

    assert result.speech_text == "presents Model seven hundred today."
    assert result.subtitle_text == source
    assert result.canonical_text == source


def test_subtitle_replace_does_not_change_speech_text() -> None:
    source = "Product X is now available."
    pack = _pack(
        _rule("subtitle_replace", match="Product X", replacement="Product X Pro")
    )

    result = _project(source, pack)

    assert result.subtitle_text == "Product X Pro is now available."
    assert result.speech_text == source
    assert result.canonical_text == source


def test_entity_alias_keeps_canonical_retrieval_text_and_adds_alias() -> None:
    source = "Falcon 7 appears on stage."
    pack = _pack(
        _rule("entity_alias", match="Falcon 7", replacement="F7")
    )

    result = _project(source, pack)

    assert result.canonical_text == source
    assert result.retrieval_text == "Falcon 7 appears on stage. F7"
    assert result.speech_text == source
    assert result.subtitle_text == source


def test_semantic_hint_is_separate_from_all_text_outputs() -> None:
    source = "The product is being reviewed."
    pack = _pack(
        _rule("semantic_hint", hint="Prefer scenes showing formal third-party scrutiny.")
    )

    result = _project(source, pack)

    assert result.canonical_text == source
    assert result.speech_text == source
    assert result.subtitle_text == source
    assert result.retrieval_text == source
    assert result.semantic_hints == [
        "Prefer scenes showing formal third-party scrutiny."
    ]


def test_disabled_rules_have_no_effect() -> None:
    source = "Model 700 is shown."
    pack = _pack(
        _rule(
            "pronunciation",
            match="Model 700",
            replacement="Model seven hundred",
            enabled=False,
        ),
        _rule(
            "semantic_hint",
            hint="This disabled hint must not be applied.",
            enabled=False,
        ),
    )

    result = _project(source, pack)

    assert result.canonical_text == source
    assert result.speech_text == source
    assert result.subtitle_text == source
    assert result.retrieval_text == source
    assert result.semantic_hints == []


def test_rule_validation_is_strict_by_kind() -> None:
    models = _rules_module()

    with pytest.raises(Exception):
        models.ProjectRule(kind=models.RuleKind.PRONUNCIATION, match="Model 700")

    with pytest.raises(Exception):
        models.ProjectRule(
            kind=models.RuleKind.SEMANTIC_HINT,
            match="unexpected",
            hint="A valid hint",
        )

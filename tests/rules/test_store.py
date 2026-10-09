from uuid import uuid4

import pytest

from clipatlas.rules.models import ProjectRule, RuleKind, RulePackStatus


def _store(tmp_path):
    try:
        from clipatlas.rules.store import ProjectRuleStore
    except ModuleNotFoundError:
        pytest.fail("clipatlas.rules.store is not implemented yet")
    return ProjectRuleStore(tmp_path / "rules.sqlite3")


def _pronunciation(match: str, replacement: str) -> ProjectRule:
    return ProjectRule(
        kind=RuleKind.PRONUNCIATION,
        match=match,
        replacement=replacement,
    )


def test_first_saved_pack_is_revision_one_draft(tmp_path) -> None:
    store = _store(tmp_path)
    project_id = uuid4()

    pack = store.save_draft(
        project_id,
        [_pronunciation("Model 700", "Model seven hundred")],
    )

    assert pack.project_id == project_id
    assert pack.revision == 1
    assert pack.status == RulePackStatus.DRAFT
    assert pack.rules[0].match == "Model 700"
    assert store.get_active(project_id) is None


def test_saving_new_draft_increments_revision_without_overwriting_history(tmp_path) -> None:
    store = _store(tmp_path)
    project_id = uuid4()

    first = store.save_draft(
        project_id,
        [_pronunciation("Model 700", "Model seven hundred")],
    )
    second = store.save_draft(
        project_id,
        [_pronunciation("Falcon 7", "Falcon seven")],
    )

    assert first.revision == 1
    assert second.revision == 2
    revisions = store.list_revisions(project_id)
    assert [pack.revision for pack in revisions] == [2, 1]
    assert revisions[1].rules[0].match == "Model 700"


def test_activate_selects_one_revision_as_current_active_pack(tmp_path) -> None:
    store = _store(tmp_path)
    project_id = uuid4()

    first = store.save_draft(
        project_id,
        [_pronunciation("Model 700", "Model seven hundred")],
    )
    second = store.save_draft(
        project_id,
        [_pronunciation("Falcon 7", "Falcon seven")],
    )

    activated_first = store.activate(project_id, first.revision)
    assert activated_first is not None
    assert activated_first.status == RulePackStatus.ACTIVE
    assert store.get_active(project_id).revision == first.revision

    activated_second = store.activate(project_id, second.revision)
    assert activated_second is not None
    assert activated_second.status == RulePackStatus.ACTIVE
    assert store.get_active(project_id).revision == second.revision

    revisions = store.list_revisions(project_id)
    statuses = {pack.revision: pack.status for pack in revisions}
    assert statuses[first.revision] == RulePackStatus.DRAFT
    assert statuses[second.revision] == RulePackStatus.ACTIVE


def test_rule_packs_are_isolated_by_project(tmp_path) -> None:
    store = _store(tmp_path)
    project_a = uuid4()
    project_b = uuid4()

    pack_a = store.save_draft(
        project_a,
        [_pronunciation("Model 700", "Model seven hundred")],
    )
    pack_b = store.save_draft(
        project_b,
        [_pronunciation("Falcon 7", "Falcon seven")],
    )

    store.activate(project_a, pack_a.revision)
    store.activate(project_b, pack_b.revision)

    active_a = store.get_active(project_a)
    active_b = store.get_active(project_b)

    assert active_a is not None
    assert active_b is not None
    assert active_a.rules[0].match == "Model 700"
    assert active_b.rules[0].match == "Falcon 7"

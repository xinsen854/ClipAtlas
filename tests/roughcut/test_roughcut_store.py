from pathlib import Path
from uuid import UUID, uuid4

from clipatlas.roughcut.models import PlannerSettings, RoughCutPlan
from clipatlas.roughcut.store import RoughCutStore


def _plan(
    project_id: UUID,
    *,
    revision: int,
    narration_track_id: UUID | None = None,
) -> RoughCutPlan:
    return RoughCutPlan(
        project_id=project_id,
        narration_track_id=narration_track_id or uuid4(),
        narration_revision=1,
        revision=revision,
        total_duration_ms=1000,
        settings=PlannerSettings(),
        beats=[],
        clips=[],
    )


def test_saved_plan_survives_store_reopen(tmp_path: Path) -> None:
    db_path = tmp_path / "roughcut.sqlite3"
    project_id = uuid4()
    plan = _plan(project_id, revision=1)

    store = RoughCutStore(db_path)
    store.save_plan(plan)

    reopened = RoughCutStore(db_path)
    assert reopened.get_plan(plan.id) == plan


def test_historical_plan_revisions_remain_retrievable(tmp_path: Path) -> None:
    store = RoughCutStore(tmp_path / "roughcut.sqlite3")
    project_id = uuid4()
    first = _plan(project_id, revision=1)
    second = _plan(project_id, revision=2)

    store.save_plan(first)
    store.save_plan(second)

    assert store.get_plan(first.id) == first
    assert store.get_plan(second.id) == second


def test_list_plans_is_project_scoped_and_newest_revision_first(tmp_path: Path) -> None:
    store = RoughCutStore(tmp_path / "roughcut.sqlite3")
    project_id = uuid4()
    other_project_id = uuid4()
    first = _plan(project_id, revision=1)
    second = _plan(project_id, revision=2)
    other = _plan(other_project_id, revision=8)
    store.save_plan(first)
    store.save_plan(second)
    store.save_plan(other)

    assert store.list_plans(project_id) == [second, first]
    assert store.list_plans(uuid4()) == []


def test_next_plan_revision_increments_per_project(tmp_path: Path) -> None:
    store = RoughCutStore(tmp_path / "roughcut.sqlite3")
    first_project = uuid4()
    second_project = uuid4()

    assert store.next_plan_revision(first_project) == 1
    store.save_plan(_plan(first_project, revision=1))
    assert store.next_plan_revision(first_project) == 2
    assert store.next_plan_revision(second_project) == 1


def test_activate_plan_requires_matching_project(tmp_path: Path) -> None:
    store = RoughCutStore(tmp_path / "roughcut.sqlite3")
    owner_project = uuid4()
    other_project = uuid4()
    plan = _plan(owner_project, revision=1)
    store.save_plan(plan)

    assert store.activate_plan(other_project, plan.id) is False
    assert store.get_active_plan(other_project) is None
    assert store.activate_plan(owner_project, plan.id) is True
    assert store.get_active_plan(owner_project) == plan


def test_changing_active_plan_preserves_previous_history(tmp_path: Path) -> None:
    store = RoughCutStore(tmp_path / "roughcut.sqlite3")
    project_id = uuid4()
    first = _plan(project_id, revision=1)
    second = _plan(project_id, revision=2)
    store.save_plan(first)
    store.save_plan(second)

    assert store.activate_plan(project_id, first.id) is True
    assert store.get_active_plan(project_id) == first
    assert store.activate_plan(project_id, second.id) is True

    assert store.get_active_plan(project_id) == second
    assert store.get_plan(first.id) == first


def test_project_revision_and_active_state_are_isolated(tmp_path: Path) -> None:
    store = RoughCutStore(tmp_path / "roughcut.sqlite3")
    first_project = uuid4()
    second_project = uuid4()
    first = _plan(first_project, revision=1)
    second = _plan(second_project, revision=1)
    store.save_plan(first)
    store.save_plan(second)

    assert store.activate_plan(first_project, first.id) is True
    assert store.activate_plan(second_project, second.id) is True

    assert store.get_active_plan(first_project) == first
    assert store.get_active_plan(second_project) == second
    assert store.next_plan_revision(first_project) == 2
    assert store.next_plan_revision(second_project) == 2


def test_unknown_plan_returns_none(tmp_path: Path) -> None:
    store = RoughCutStore(tmp_path / "roughcut.sqlite3")

    assert store.get_plan(uuid4()) is None
    assert store.get_active_plan(uuid4()) is None


def test_store_accepts_nested_database_path(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "roughcut" / "roughcut.sqlite3"

    RoughCutStore(db_path)

    assert db_path.exists()


def test_plan_identity_is_not_reassigned_on_save(tmp_path: Path) -> None:
    store = RoughCutStore(tmp_path / "roughcut.sqlite3")
    project_id = uuid4()
    plan = _plan(project_id, revision=1)

    store.save_plan(plan)
    loaded = store.get_plan(plan.id)

    assert loaded is not None
    assert loaded.id == plan.id
    assert loaded.revision == 1

from pathlib import Path

from clipatlas.projects.store import ProjectStore


def test_project_store_create_list_update(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "projects.sqlite3")
    created = store.create("电影解说 0903", "测试项目")

    assert store.get(created.id) == created
    assert [project.id for project in store.list_projects()] == [created.id]

    updated = store.update(
        created.id,
        name="电影解说 0903 v2",
        description=None,
        description_set=True,
    )
    assert updated is not None
    assert updated.name == "电影解说 0903 v2"
    assert updated.description is None
    assert updated.updated_at >= created.updated_at


def test_project_store_update_preserves_omitted_description(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "projects.sqlite3")
    created = store.create("项目 A", "保留说明")

    updated = store.update(
        created.id,
        name="项目 B",
        description=None,
        description_set=False,
    )

    assert updated is not None
    assert updated.name == "项目 B"
    assert updated.description == "保留说明"


def test_project_store_update_missing_project_returns_none(tmp_path: Path) -> None:
    from uuid import uuid4

    store = ProjectStore(tmp_path / "projects.sqlite3")

    assert (
        store.update(
            uuid4(),
            name="不存在",
            description=None,
            description_set=False,
        )
        is None
    )

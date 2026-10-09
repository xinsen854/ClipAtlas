from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from clipatlas.main import create_app
from clipatlas.projects.store import ProjectStore


def _client(tmp_path: Path) -> TestClient:
    app = create_app()
    app.state.project_store = ProjectStore(tmp_path / "projects.sqlite3")
    return TestClient(app)


def test_projects_crud(tmp_path: Path) -> None:
    client = _client(tmp_path)
    created = client.post(
        "/api/v1/projects",
        json={"name": "电影解说 0903", "description": "第一版"},
    )
    assert created.status_code == 201
    project_id = created.json()["id"]

    listed = client.get("/api/v1/projects")
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == project_id

    detail = client.get(f"/api/v1/projects/{project_id}")
    assert detail.status_code == 200
    assert detail.json()["description"] == "第一版"

    updated = client.patch(
        f"/api/v1/projects/{project_id}",
        json={"name": "电影解说 0903 v2"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "电影解说 0903 v2"
    assert updated.json()["description"] == "第一版"

    cleared = client.patch(
        f"/api/v1/projects/{project_id}",
        json={"description": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["description"] is None


def test_projects_unknown_uuid_returns_404(tmp_path: Path) -> None:
    client = _client(tmp_path)
    missing = uuid4()

    assert client.get(f"/api/v1/projects/{missing}").status_code == 404
    assert (
        client.patch(
            f"/api/v1/projects/{missing}",
            json={"name": "不存在"},
        ).status_code
        == 404
    )


def test_project_patch_rejects_empty_name(tmp_path: Path) -> None:
    client = _client(tmp_path)
    created = client.post("/api/v1/projects", json={"name": "项目 A"})
    assert created.status_code == 201

    response = client.patch(
        f"/api/v1/projects/{created.json()['id']}",
        json={"name": ""},
    )

    assert response.status_code == 422

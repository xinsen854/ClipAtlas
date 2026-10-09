from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from clipatlas.api.errors import register_error_handlers
from clipatlas.api.routes.system import router as system_router
from clipatlas.exports.models import JianyingDraftArtifact, JianyingMode
from clipatlas.system.artifacts import GeneratedArtifactRegistry
from clipatlas.system.shell import LocalShellService


class RecordingLauncher:
    def __init__(self) -> None:
        self.opened: list[Path] = []
        self.launched: list[Path] = []

    def open_folder(self, path: Path) -> None:
        self.opened.append(path)

    def launch_executable(self, path: Path) -> None:
        self.launched.append(path)


def _artifact(plan_id, output_path: Path) -> JianyingDraftArtifact:
    return JianyingDraftArtifact(
        plan_id=plan_id,
        project_id=uuid4(),
        narration_track_id=uuid4(),
        draft_name=output_path.name,
        output_path=output_path,
        mode=JianyingMode.PORTABLE,
        backend_name="test",
        backend_version="1",
        total_duration_ms=5000,
    )


def _app(service: LocalShellService) -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(system_router)
    app.state.local_shell_service = service
    return app


def test_open_export_folder_accepts_only_plan_id(tmp_path: Path) -> None:
    draft_root = tmp_path / "drafts"
    draft = draft_root / "Trusted Draft"
    draft.mkdir(parents=True)
    plan_id = uuid4()
    registry = GeneratedArtifactRegistry()
    registry.register_jianying(_artifact(plan_id, draft))
    launcher = RecordingLauncher()
    client = TestClient(
        _app(
            LocalShellService(
                registry=registry,
                draft_root=draft_root,
                launcher=launcher,
                platform="win32",
            )
        )
    )

    response = client.post(
        "/api/v1/system/open-export-folder",
        json={"plan_id": str(plan_id)},
    )

    assert response.status_code == 200
    assert response.json() == {
        "action": "opened_export_folder",
        "path": str(draft.resolve()),
    }
    assert launcher.opened == [draft.resolve()]

    rejected = client.post(
        "/api/v1/system/open-export-folder",
        json={"plan_id": str(plan_id), "path": str(tmp_path)},
    )
    assert rejected.status_code == 422
    assert launcher.opened == [draft.resolve()]


def test_open_export_folder_returns_stable_unknown_artifact_error(tmp_path: Path) -> None:
    client = TestClient(
        _app(
            LocalShellService(
                registry=GeneratedArtifactRegistry(),
                draft_root=tmp_path,
                launcher=RecordingLauncher(),
                platform="win32",
            )
        )
    )

    response = client.post(
        "/api/v1/system/open-export-folder",
        json={"plan_id": str(uuid4())},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "generated_artifact_not_found"


def test_open_jianying_uses_server_configuration_without_request_path(tmp_path: Path) -> None:
    executable = tmp_path / "JianyingPro.exe"
    executable.write_bytes(b"stub")
    launcher = RecordingLauncher()
    client = TestClient(
        _app(
            LocalShellService(
                registry=GeneratedArtifactRegistry(),
                draft_root=tmp_path,
                jianying_executable=executable,
                launcher=launcher,
                platform="win32",
            )
        )
    )

    response = client.post("/api/v1/system/open-jianying")

    assert response.status_code == 200
    assert response.json() == {
        "action": "launched_jianying",
        "path": str(executable.resolve()),
    }
    assert launcher.launched == [executable.resolve()]


def test_open_jianying_returns_stable_not_configured_error(tmp_path: Path) -> None:
    client = TestClient(
        _app(
            LocalShellService(
                registry=GeneratedArtifactRegistry(),
                draft_root=tmp_path,
                launcher=RecordingLauncher(),
                platform="win32",
            )
        )
    )

    response = client.post("/api/v1/system/open-jianying")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "local_system_not_configured"

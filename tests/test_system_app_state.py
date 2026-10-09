import sys
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from clipatlas.app_state import build_local_shell_service
from clipatlas.exports.models import DEFAULT_JIANYING_DRAFT_ROOT
from clipatlas.main import create_app
from clipatlas.system.artifacts import GeneratedArtifactRegistry
from clipatlas.system.shell import LocalShellService


def test_local_shell_service_uses_server_side_jianying_configuration(
    tmp_path: Path,
    monkeypatch,
) -> None:
    draft_root = tmp_path / "drafts"
    install_dir = tmp_path / "install"
    executable = tmp_path / "custom" / "JianyingCustom.exe"
    monkeypatch.setenv("CLIPATLAS_JIANYING_DRAFT_ROOT", str(draft_root))
    monkeypatch.setenv("CLIPATLAS_JIANYING_INSTALL_DIR", str(install_dir))
    monkeypatch.setenv("CLIPATLAS_JIANYING_EXECUTABLE", str(executable))
    registry = GeneratedArtifactRegistry()

    service = build_local_shell_service(registry)

    assert isinstance(service, LocalShellService)
    assert service._registry is registry
    assert service._draft_root == draft_root.resolve()
    assert service._jianying_install_dir == install_dir.resolve()
    assert service._jianying_executable == executable.resolve()


def test_local_shell_service_uses_default_draft_root(monkeypatch) -> None:
    monkeypatch.delenv("CLIPATLAS_JIANYING_DRAFT_ROOT", raising=False)
    monkeypatch.delenv("CLIPATLAS_JIANYING_INSTALL_DIR", raising=False)
    monkeypatch.delenv("CLIPATLAS_JIANYING_EXECUTABLE", raising=False)

    service = build_local_shell_service(GeneratedArtifactRegistry())

    assert service._draft_root == Path(DEFAULT_JIANYING_DRAFT_ROOT).resolve()
    assert service._jianying_install_dir is None
    assert service._jianying_executable is None


def test_create_app_shares_generated_artifact_registry_with_local_shell(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CLIPATLAS_PROJECT_DB", str(tmp_path / "projects.sqlite3"))
    monkeypatch.setenv("CLIPATLAS_VIDEO_ROOT", str(tmp_path / "videos"))
    monkeypatch.setenv("CLIPATLAS_LIBRARY_DB", str(tmp_path / "library.sqlite3"))
    monkeypatch.setenv("CLIPATLAS_LIBRARY_CACHE_ROOT", str(tmp_path / "cache"))
    monkeypatch.setenv("CLIPATLAS_NARRATION_ROOT", str(tmp_path / "narration"))
    monkeypatch.setenv("CLIPATLAS_ROUGHCUT_DB", str(tmp_path / "roughcut.sqlite3"))
    monkeypatch.setenv("CLIPATLAS_EXPORT_ROOT", str(tmp_path / "exports"))
    monkeypatch.setenv("CLIPATLAS_JIANYING_DRAFT_ROOT", str(tmp_path / "drafts"))
    monkeypatch.delenv("CLIPATLAS_EMBEDDING_API_KEY", raising=False)
    monkeypatch.delenv("CLIPATLAS_QWEN_API_KEY", raising=False)
    monkeypatch.delenv("CLIPATLAS_SPEECH_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    app = create_app()

    registry = app.state.generated_artifact_registry
    assert isinstance(registry, GeneratedArtifactRegistry)
    assert isinstance(app.state.local_shell_service, LocalShellService)
    assert app.state.local_shell_service._registry is registry

    client = TestClient(app)
    folder_response = client.post(
        "/api/v1/system/open-export-folder",
        json={"plan_id": str(uuid4())},
    )
    assert folder_response.status_code == 404
    assert folder_response.json()["error"]["code"] == "generated_artifact_not_found"

    launch_response = client.post("/api/v1/system/open-jianying")
    assert launch_response.status_code == 409
    expected = "local_system_not_configured" if sys.platform == "win32" else "local_system_unsupported"
    assert launch_response.json()["error"]["code"] == expected

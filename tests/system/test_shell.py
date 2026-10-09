from pathlib import Path
from uuid import uuid4

import pytest

from clipatlas.exports.models import JianyingDraftArtifact, JianyingMode
from clipatlas.system.artifacts import GeneratedArtifactRegistry
from clipatlas.system.shell import (
    GeneratedArtifactNotFoundError,
    GeneratedArtifactPathError,
    LocalShellService,
    LocalSystemConfigurationError,
    LocalSystemUnsupportedError,
)


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


def test_open_generated_export_folder_uses_only_registered_artifact(tmp_path: Path) -> None:
    draft_root = tmp_path / "drafts"
    draft = draft_root / "Trusted Draft"
    draft.mkdir(parents=True)
    plan_id = uuid4()
    registry = GeneratedArtifactRegistry()
    registry.register_jianying(_artifact(plan_id, draft))
    launcher = RecordingLauncher()
    service = LocalShellService(
        registry=registry,
        draft_root=draft_root,
        launcher=launcher,
        platform="win32",
    )

    opened = service.open_generated_export_folder(plan_id)

    assert opened == draft.resolve()
    assert launcher.opened == [draft.resolve()]


def test_open_generated_export_folder_rejects_unknown_or_untrusted_path(tmp_path: Path) -> None:
    draft_root = tmp_path / "drafts"
    draft_root.mkdir()
    outside = tmp_path / "outside" / "Draft"
    outside.mkdir(parents=True)
    registry = GeneratedArtifactRegistry()
    launcher = RecordingLauncher()
    service = LocalShellService(
        registry=registry,
        draft_root=draft_root,
        launcher=launcher,
        platform="win32",
    )

    with pytest.raises(GeneratedArtifactNotFoundError):
        service.open_generated_export_folder(uuid4())

    plan_id = uuid4()
    registry.register_jianying(_artifact(plan_id, outside))
    with pytest.raises(GeneratedArtifactPathError):
        service.open_generated_export_folder(plan_id)

    assert launcher.opened == []


def test_open_generated_export_folder_requires_existing_directory(tmp_path: Path) -> None:
    draft_root = tmp_path / "drafts"
    draft_root.mkdir()
    missing = draft_root / "Missing Draft"
    plan_id = uuid4()
    registry = GeneratedArtifactRegistry()
    registry.register_jianying(_artifact(plan_id, missing))
    service = LocalShellService(
        registry=registry,
        draft_root=draft_root,
        launcher=RecordingLauncher(),
        platform="win32",
    )

    with pytest.raises(GeneratedArtifactPathError):
        service.open_generated_export_folder(plan_id)


def test_launch_jianying_prefers_explicit_executable(tmp_path: Path) -> None:
    explicit = tmp_path / "custom" / "JianyingCustom.exe"
    explicit.parent.mkdir()
    explicit.write_bytes(b"stub")
    fallback_dir = tmp_path / "install"
    fallback_dir.mkdir()
    (fallback_dir / "JianyingPro.exe").write_bytes(b"fallback")
    launcher = RecordingLauncher()
    service = LocalShellService(
        registry=GeneratedArtifactRegistry(),
        draft_root=tmp_path,
        jianying_executable=explicit,
        jianying_install_dir=fallback_dir,
        launcher=launcher,
        platform="win32",
    )

    launched = service.launch_jianying()

    assert launched == explicit.resolve()
    assert launcher.launched == [explicit.resolve()]


def test_launch_jianying_uses_only_fixed_install_dir_candidates(tmp_path: Path) -> None:
    install_dir = tmp_path / "install"
    nested = install_dir / "nested"
    nested.mkdir(parents=True)
    (nested / "Something.exe").write_bytes(b"wrong")
    jianying = install_dir / "Jianying.exe"
    jianying.write_bytes(b"stub")
    launcher = RecordingLauncher()
    service = LocalShellService(
        registry=GeneratedArtifactRegistry(),
        draft_root=tmp_path,
        jianying_install_dir=install_dir,
        launcher=launcher,
        platform="win32",
    )

    launched = service.launch_jianying()

    assert launched == jianying.resolve()
    assert launcher.launched == [jianying.resolve()]


def test_launch_jianying_rejects_non_windows_and_missing_configuration(tmp_path: Path) -> None:
    executable = tmp_path / "JianyingPro.exe"
    executable.write_bytes(b"stub")
    non_windows = LocalShellService(
        registry=GeneratedArtifactRegistry(),
        draft_root=tmp_path,
        jianying_executable=executable,
        launcher=RecordingLauncher(),
        platform="linux",
    )
    unconfigured = LocalShellService(
        registry=GeneratedArtifactRegistry(),
        draft_root=tmp_path,
        launcher=RecordingLauncher(),
        platform="win32",
    )

    with pytest.raises(LocalSystemUnsupportedError):
        non_windows.launch_jianying()
    with pytest.raises(LocalSystemConfigurationError):
        unconfigured.launch_jianying()

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Protocol
from uuid import UUID

from clipatlas.system.artifacts import GeneratedArtifactRegistry


class LocalSystemError(RuntimeError):
    pass


class GeneratedArtifactNotFoundError(LocalSystemError):
    pass


class GeneratedArtifactPathError(LocalSystemError):
    pass


class LocalSystemConfigurationError(LocalSystemError):
    pass


class LocalSystemUnsupportedError(LocalSystemError):
    pass


class LocalSystemActionFailedError(LocalSystemError):
    pass


class LocalLauncher(Protocol):
    def open_folder(self, path: Path) -> None: ...

    def open_file(self, path: Path) -> None: ...

    def launch_executable(self, path: Path) -> None: ...


class SubprocessLocalLauncher:
    def _spawn(self, args: list[str], *, cwd: Path | None = None) -> None:
        try:
            subprocess.Popen(
                args,
                cwd=str(cwd) if cwd is not None else None,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise LocalSystemActionFailedError(str(exc)) from exc

    def open_folder(self, path: Path) -> None:
        if sys.platform == "win32":
            command = ["explorer.exe", str(path)]
        elif sys.platform == "darwin":
            command = ["open", str(path)]
        else:
            command = ["xdg-open", str(path)]
        self._spawn(command)

    def open_file(self, path: Path) -> None:
        if sys.platform == "win32":
            command = ["cmd.exe", "/c", "start", "", str(path)]
        elif sys.platform == "darwin":
            command = ["open", str(path)]
        else:
            command = ["xdg-open", str(path)]
        self._spawn(command)

    def launch_executable(self, path: Path) -> None:
        self._spawn([str(path)], cwd=path.parent)


class LocalShellService:
    def __init__(
        self,
        *,
        registry: GeneratedArtifactRegistry,
        draft_root: Path | None,
        jianying_executable: Path | None = None,
        jianying_install_dir: Path | None = None,
        launcher: LocalLauncher | None = None,
        platform: str | None = None,
    ) -> None:
        self._registry = registry
        self._draft_root = self._normalize(draft_root)
        self._jianying_executable = self._normalize(jianying_executable)
        self._jianying_install_dir = self._normalize(jianying_install_dir)
        self._launcher = launcher or SubprocessLocalLauncher()
        self._platform = platform or sys.platform

    @staticmethod
    def _normalize(path: Path | None) -> Path | None:
        if path is None:
            return None
        return path.expanduser().resolve(strict=False)

    def open_generated_export_folder(self, plan_id: UUID) -> Path:
        artifact = self._registry.get_jianying(plan_id)
        if artifact is None:
            raise GeneratedArtifactNotFoundError(
                f"No generated Jianying artifact is registered for plan {plan_id}"
            )

        draft_root = self._draft_root
        if draft_root is None:
            raise LocalSystemConfigurationError("Jianying draft root is not configured")

        try:
            output_path = artifact.output_path.expanduser().resolve(strict=True)
        except OSError as exc:
            raise GeneratedArtifactPathError("Generated draft folder does not exist") from exc
        if not output_path.is_dir():
            raise GeneratedArtifactPathError("Generated artifact path is not a directory")
        if output_path != draft_root and draft_root not in output_path.parents:
            raise GeneratedArtifactPathError(
                "Generated draft folder is outside the configured Jianying draft root"
            )

        self._launcher.open_folder(output_path)
        return output_path

    def open_hypit_output(self, path: Path, workspace: Path) -> Path:
        try:
            output_path = path.expanduser().resolve(strict=True)
            workspace_path = workspace.expanduser().resolve(strict=True)
        except OSError as exc:
            raise GeneratedArtifactPathError("Generated video does not exist") from exc
        if not output_path.is_file():
            raise GeneratedArtifactPathError("Generated video is not a file")
        if workspace_path not in output_path.parents:
            raise GeneratedArtifactPathError("Generated video is outside the Hypit workspace")
        self._launcher.open_file(output_path)
        return output_path

    def launch_jianying(self) -> Path:
        if self._platform != "win32":
            raise LocalSystemUnsupportedError(
                "Launching Jianying is only supported on Windows"
            )

        executable = self._resolve_jianying_executable()
        self._launcher.launch_executable(executable)
        return executable

    def _resolve_jianying_executable(self) -> Path:
        explicit = self._jianying_executable
        if explicit is not None:
            if not explicit.is_file():
                raise LocalSystemConfigurationError(
                    "Configured Jianying executable does not exist or is not a file"
                )
            return explicit

        install_dir = self._jianying_install_dir
        if install_dir is None:
            raise LocalSystemConfigurationError("Jianying executable is not configured")
        if not install_dir.is_dir():
            raise LocalSystemConfigurationError(
                "Configured Jianying install directory does not exist"
            )

        for filename in ("JianyingPro.exe", "Jianying.exe"):
            candidate = install_dir / filename
            if candidate.is_file():
                return candidate.resolve()

        raise LocalSystemConfigurationError(
            "No supported Jianying executable was found in the configured install directory"
        )

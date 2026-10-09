from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

HYPIT_VERSION = "0.2.17"
HYPIT_COMMIT = "e8f94006e1eed9b299448fe5bce6afa5646e2ba5"

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_PACKAGE = re.compile(r"^(?:@[A-Za-z0-9._-]+/)?[A-Za-z0-9][A-Za-z0-9._-]*$")
_REFERENCE_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
_INPUT_EXTENSIONS = _REFERENCE_EXTENSIONS | {".png", ".jpg", ".jpeg", ".webp", ".wav", ".mp3", ".m4a", ".aac"}
_BUILD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_WAVESPEED_PROVIDER = "@hypit/provider-wavespeed"


class HypitConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    distribution_root: str
    workspace: str
    run_file: str
    endpoint: str = "hypihub.default"
    provider_package: str = "@hypit/provider-hypihub"
    base_url: str | None = "https://hypit.ai"
    base_url_field: str = "baseUrl"
    credential_field: str = "apiKey"
    provider_config: dict[str, Any] = Field(default_factory=dict)
    api_key_configured: bool = False

    @field_validator("endpoint", "base_url_field", "credential_field")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        normalized = value.strip()
        if not _IDENTIFIER.fullmatch(normalized):
            raise ValueError("must be a simple identifier")
        return normalized

    @field_validator("provider_package")
    @classmethod
    def validate_package(cls, value: str) -> str:
        normalized = value.strip()
        if not _PACKAGE.fullmatch(normalized):
            raise ValueError("must be an installed Node package name")
        return normalized

    @field_validator("distribution_root", "workspace", "run_file")
    @classmethod
    def normalize_path(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("path must not be empty")
        return normalized

    @field_validator("base_url")
    @classmethod
    def normalize_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().rstrip("/")
        return normalized or None


class HypitConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    distribution_root: str
    workspace: str
    run_file: str
    endpoint: str = "hypihub.default"
    provider_package: str = "@hypit/provider-hypihub"
    base_url: str | None = "https://hypit.ai"
    base_url_field: str = "baseUrl"
    credential_field: str = "apiKey"
    provider_config: dict[str, Any] = Field(default_factory=dict)
    api_key: str | None = None
    clear_api_key: bool = False


class HypitStatus(BaseModel):
    configured: bool
    running: bool
    url: str | None
    pid: int | None
    version: str = HYPIT_VERSION
    commit: str = HYPIT_COMMIT


class HypitConnectionResult(BaseModel):
    ok: bool
    message: str


class HypitReference(BaseModel):
    name: str
    size: int
    modified_at: datetime


class HypitInput(BaseModel):
    name: str
    kind: str
    size: int
    modified_at: datetime


class HypitBuild(BaseModel):
    id: str
    created_at: datetime | None = None
    title: str | None = None
    outcome: str
    targets: list[str] = Field(default_factory=list)
    output_count: int = 0


class HypitConfigurationError(RuntimeError):
    pass


class HypitService:
    def __init__(self, config_path: Path) -> None:
        self._config_path = config_path
        self._process: subprocess.Popen[bytes] | None = None
        self._log_handle: Any | None = None
        self._url: str | None = None
        self._lock = threading.RLock()

    @classmethod
    def from_environment(cls) -> HypitService:
        return cls(Path(os.getenv("CLIPATLAS_HYPIT_CONFIG", "./data/hypit/config.json")))

    def config(self) -> HypitConfig:
        if self._config_path.exists():
            return HypitConfig.model_validate_json(self._config_path.read_text(encoding="utf-8"))
        root = self._config_path.parent
        return HypitConfig(
            distribution_root=str((root / "distribution").resolve()),
            workspace=str((root / "workspace").resolve()),
            run_file=str((root / "workspace" / "build.svrun").resolve()),
        )

    def update(self, update: HypitConfigUpdate) -> HypitConfig:
        current = self.config()
        api_key = (update.api_key or "").strip()
        configured = (
            current.api_key_configured if current.endpoint == update.endpoint.strip() else False
        )
        candidate = HypitConfig(
            **update.model_dump(exclude={"api_key", "clear_api_key"}),
            api_key_configured=configured,
        )
        self._validate_paths(candidate, require_existing=False)
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        runtime_path = self._write_runtime(candidate)

        if update.clear_api_key:
            self._run_auth(candidate, runtime_path, action="logout")
            configured = False
        elif api_key:
            self._run_auth(candidate, runtime_path, action="login", secret=api_key)
            configured = True

        saved = candidate.model_copy(update={"api_key_configured": configured})
        self._write_config(saved)
        return saved

    def status(self) -> HypitStatus:
        process = self._process
        running = process is not None and process.poll() is None
        if not running:
            self._close_process_resources()
        return HypitStatus(
            configured=self._config_path.exists(),
            running=running,
            url=self._url if running else None,
            pid=process.pid if process is not None and running else None,
        )

    def test_connection(
        self,
        api_key: str | None = None,
        *,
        provider_package: str | None = None,
        base_url: str | None = None,
    ) -> HypitConnectionResult:
        config = self.config()
        transient_key = (api_key or "").strip()
        if transient_key:
            selected_provider = (provider_package or config.provider_package).strip()
            selected_base = (base_url or config.base_url or "").strip()
            if selected_provider == _WAVESPEED_PROVIDER:
                url = f"{(selected_base or 'https://api.wavespeed.ai/api/v3').rstrip('/')}/models"
            elif selected_provider == "@hypit/provider-hypihub":
                root = (selected_base or "https://hypit.ai").rstrip("/")
                url = f"{root}/models" if root.endswith("/v1") else f"{root}/v1/models"
            else:
                return HypitConnectionResult(ok=False, message="当前 Provider 不支持内置连接测试。")
            try:
                response = httpx.get(
                    url,
                    headers={"Authorization": f"Bearer {transient_key}"},
                    timeout=20,
                )
            except httpx.HTTPError:
                return HypitConnectionResult(ok=False, message="无法连接模型服务，请检查网络。")
            if response.status_code == 401:
                return HypitConnectionResult(ok=False, message="API Key 无效或已过期。")
            if response.status_code == 402:
                return HypitConnectionResult(ok=False, message="账户余额不足。")
            if response.is_error:
                return HypitConnectionResult(
                    ok=False,
                    message=f"模型服务返回 HTTP {response.status_code}。",
                )
            return HypitConnectionResult(ok=True, message="连接成功，API Key 可用。")

        if not config.api_key_configured:
            return HypitConnectionResult(ok=False, message="请先输入或保存 API Key。")
        runtime_path = self._write_runtime(config)
        try:
            payload = self._run_cli_json(
                config,
                [
                    "doctor",
                    "--runtime",
                    str(runtime_path),
                    "--endpoint",
                    config.endpoint,
                    "--workspace",
                    str(Path(config.workspace).resolve()),
                ],
                timeout=60,
            )
        except HypitConfigurationError as exc:
            return HypitConnectionResult(ok=False, message=str(exc))
        return HypitConnectionResult(
            ok=bool(payload.get("ok")),
            message="连接成功，已保存的 API Key 可用。"
            if payload.get("ok")
            else "连接失败，请检查 API Key 和模型权限。",
        )

    def start(self) -> HypitStatus:
        with self._lock:
            current = self.status()
            if current.running:
                return current

            config = self.config()
            self._validate_paths(config, require_existing=True)
            runtime_path = self._write_runtime(config)
            port = self._free_port(5179)
            command = self._studio_command(config, runtime_path, port)

            log_path = self._config_path.parent / "logs" / "studio.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log_handle = open(log_path, "ab", buffering=0)  # noqa: SIM115
            self._process = subprocess.Popen(
                command,
                cwd=config.workspace,
                stdin=subprocess.DEVNULL,
                stdout=self._log_handle,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self._url = f"http://127.0.0.1:{port}"

            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if self._process.poll() is not None:
                    self._close_process_resources()
                    raise HypitConfigurationError(
                        f"Hypit Studio exited during startup; inspect {log_path}"
                    )
                if self._port_is_open(port):
                    return self.status()
                time.sleep(0.2)

            self.stop()
            raise HypitConfigurationError(
                f"Hypit Studio did not listen within 30 seconds; inspect {log_path}"
            )

    def stop(self) -> HypitStatus:
        with self._lock:
            process = self._process
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            self._close_process_resources()
            return self.status()

    def references(self) -> list[HypitReference]:
        root = self._reference_root()
        if not root.exists():
            return []
        return [
            HypitReference(
                name=path.name,
                size=path.stat().st_size,
                modified_at=datetime.fromtimestamp(path.stat().st_mtime, tz=UTC),
            )
            for path in sorted(root.iterdir(), key=lambda item: item.name.lower())
            if path.is_file() and path.suffix.lower() in _REFERENCE_EXTENSIONS
        ]

    def import_reference(self, name: str, source: BinaryIO, *, max_bytes: int) -> HypitReference:
        destination = self._reference_path(name)
        if destination.exists():
            raise HypitConfigurationError(f"Reference video already exists: {destination.name}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".upload")
        size = 0
        try:
            with temporary.open("wb") as target:
                while chunk := source.read(1024 * 1024):
                    size += len(chunk)
                    if size > max_bytes:
                        raise HypitConfigurationError("Reference video exceeds the 2 GB limit")
                    target.write(chunk)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        stat = destination.stat()
        return HypitReference(
            name=destination.name,
            size=stat.st_size,
            modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
        )

    def delete_reference(self, name: str) -> None:
        path = self._reference_path(name)
        if not path.is_file():
            raise HypitConfigurationError(f"Reference video does not exist: {path.name}")
        path.unlink()

    def inputs(self) -> list[HypitInput]:
        root = self._input_root()
        if not root.exists():
            return []
        result: list[HypitInput] = []
        for path in sorted(root.rglob("*"), key=lambda item: item.name.lower()):
            if path.is_file() and path.suffix.lower() in _INPUT_EXTENSIONS:
                stat = path.stat()
                result.append(HypitInput(
                    name=path.name,
                    kind=path.parent.name,
                    size=stat.st_size,
                    modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                ))
        return result

    def import_input(self, kind: str, name: str, source: BinaryIO, *, max_bytes: int) -> HypitInput:
        if kind not in {"people", "products", "audio"}:
            raise HypitConfigurationError("Input kind is invalid")
        safe_name = Path(name).name
        if safe_name != name or not safe_name or Path(safe_name).suffix.lower() not in _INPUT_EXTENSIONS:
            raise HypitConfigurationError("Input must be a supported media file name")
        destination = self._input_root() / kind / safe_name
        if destination.exists():
            raise HypitConfigurationError(f"Input file already exists: {destination.name}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".upload")
        size = 0
        try:
            with temporary.open("wb") as target:
                while chunk := source.read(1024 * 1024):
                    size += len(chunk)
                    if size > max_bytes:
                        raise HypitConfigurationError("Input file exceeds the 2 GB limit")
                    target.write(chunk)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        stat = destination.stat()
        return HypitInput(name=destination.name, kind=kind, size=stat.st_size, modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC))

    def brief(self) -> str:
        path = Path(self.config().workspace).resolve() / "CLIPATLAS_BRIEF.md"
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    def update_brief(self, text: str) -> None:
        if len(text) > 20_000:
            raise HypitConfigurationError("Brief is too long")
        path = Path(self.config().workspace).resolve() / "CLIPATLAS_BRIEF.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text.strip() + "\n", encoding="utf-8")

    def submit_build(self, title: str | None = None) -> dict[str, Any]:
        config = self.config()
        self._validate_paths(config, require_existing=True)
        runtime_path = self._write_runtime(config)
        command = [
            "build",
            str(Path(config.run_file).resolve()),
            "--runtime",
            str(runtime_path),
            "--workspace",
            str(Path(config.workspace).resolve()),
            "--package-root",
            str(Path(config.workspace).resolve()),
        ]
        if title and title.strip():
            command.extend(["--title", title.strip()])
        return self._run_cli_json(config, command, timeout=120)

    def builds(self) -> list[HypitBuild]:
        config = self.config()
        payload = self._run_cli_json(
            config,
            ["builds", "--workspace", str(Path(config.workspace).resolve()), "--limit", "50", "--verbose"],
        )
        return [
            HypitBuild(
                id=str(item["id"]),
                created_at=item.get("createdAt"),
                title=item.get("title"),
                outcome=str(item.get("outcome", "unknown")),
                targets=[str(value) for value in item.get("targets", [])],
                output_count=int(item.get("outputCount", 0)),
            )
            for item in payload.get("builds", [])
        ]

    def update_build_title(self, build_id: str, title: str) -> None:
        config = self.config()
        self._validate_build_id(build_id)
        self._run_cli_json(
            config,
            [
                "result",
                "edit",
                build_id,
                "--title",
                title.strip(),
                "--workspace",
                str(Path(config.workspace).resolve()),
            ],
        )

    def export_output(self, build_id: str, output: str) -> Path:
        config = self.config()
        self._validate_build_id(build_id)
        safe_output = Path(output).name
        if safe_output != output or not safe_output:
            raise HypitConfigurationError("Output name is invalid")
        destination = Path(config.workspace).resolve() / "exports" / build_id / safe_output
        destination.parent.mkdir(parents=True, exist_ok=True)
        # `hypit get` refuses to overwrite an existing destination. Export is
        # intentionally idempotent so clicking the button again downloads the
        # already generated artifact instead of surfacing a CLI error.
        if destination.is_file():
            return destination
        self._run_cli_json(
            config,
            [
                "get",
                build_id,
                "--output",
                output,
                "--to",
                str(destination),
                "--workspace",
                str(Path(config.workspace).resolve()),
            ],
            timeout=120,
        )
        if not destination.is_file():
            raise HypitConfigurationError("Hypit did not produce the requested export")
        return destination

    def _validate_paths(self, config: HypitConfig, *, require_existing: bool) -> None:
        workspace = Path(config.workspace).resolve()
        run_file = Path(config.run_file).resolve()
        try:
            run_file.relative_to(workspace)
        except ValueError as exc:
            raise HypitConfigurationError("Hypit Run file must be inside its workspace") from exc

        if not require_existing:
            workspace.mkdir(parents=True, exist_ok=True)
            return

        launcher = Path(config.distribution_root).resolve() / "bin" / "hypit.mjs"
        if not launcher.is_file():
            raise HypitConfigurationError(f"Hypit launcher is missing: {launcher}")
        if not run_file.is_file():
            raise HypitConfigurationError(f"Hypit Run file is missing: {run_file}")
        if shutil.which("node") is None:
            raise HypitConfigurationError("Node.js is not available on PATH")

    def _reference_root(self) -> Path:
        return Path(self.config().workspace).resolve() / "assets" / "references"

    def _input_root(self) -> Path:
        return Path(self.config().workspace).resolve() / "assets" / "inputs"

    def _reference_path(self, name: str) -> Path:
        safe_name = Path(name).name
        if safe_name != name or not safe_name or Path(safe_name).suffix.lower() not in _REFERENCE_EXTENSIONS:
            raise HypitConfigurationError("Reference must be a supported video file name")
        return self._reference_root() / safe_name

    @staticmethod
    def _validate_build_id(build_id: str) -> None:
        if not _BUILD_ID.fullmatch(build_id):
            raise HypitConfigurationError("Build id is invalid")

    def _run_cli_json(
        self,
        config: HypitConfig,
        arguments: list[str],
        *,
        timeout: int = 60,
    ) -> dict[str, Any]:
        launcher = Path(config.distribution_root).resolve() / "bin" / "hypit.mjs"
        if not launcher.is_file():
            raise HypitConfigurationError(f"Hypit launcher is missing: {launcher}")
        result = subprocess.run(
            [shutil.which("node") or "node", str(launcher), *arguments, "--json"],
            cwd=config.workspace,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or "Hypit command failed"
            raise HypitConfigurationError(message)
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise HypitConfigurationError("Hypit returned invalid machine output") from exc
        if not isinstance(payload, dict):
            raise HypitConfigurationError("Hypit returned invalid machine output")
        return payload

    def _runtime_path(self, config: HypitConfig) -> Path:
        return Path(config.workspace).resolve() / ".hypit" / "clipatlas.runtime.json"

    def _write_runtime(self, config: HypitConfig) -> Path:
        self._ensure_bundled_provider(config)
        runtime_path = self._runtime_path(config)
        endpoint_config = dict(config.provider_config)
        if config.base_url is not None:
            endpoint_config[config.base_url_field] = config.base_url
        endpoint_config[config.credential_field] = {
            "store": "os",
            "key": f"clipatlas.{config.endpoint}",
        }
        payload = {
            "format": "hypit.runtime-local@1",
            "dataRoot": ".hypit/runtimes/clipatlas",
            "credentials": {
                "os": {
                    "use": "@hypit/credential-store-os",
                    "config": {"service": "clipatlas-hypit"},
                }
            },
            "endpoints": {
                config.endpoint: {
                    "use": config.provider_package,
                    "config": endpoint_config,
                },
                "media.local": {"use": "@hypit/provider-media-local"},
                "hyperframes.local": {"use": "@hypit/provider-hyperframes-local"},
            },
            "bindings": {},
        }
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_json_atomic(runtime_path, payload)
        return runtime_path

    @staticmethod
    def _ensure_bundled_provider(config: HypitConfig) -> None:
        if config.provider_package != _WAVESPEED_PROVIDER:
            return
        source = Path(__file__).with_name("wavespeed_provider")
        destination = Path(config.distribution_root).resolve() / "packages" / "provider-wavespeed"
        if not source.is_dir():
            raise HypitConfigurationError("ClipAtlas WaveSpeed Provider 缺失。")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination, dirs_exist_ok=True)

    def _write_config(self, config: HypitConfig) -> None:
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_json_atomic(
            self._config_path,
            config.model_dump(mode="json"),
        )

    @staticmethod
    def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)

    def _run_auth(
        self,
        config: HypitConfig,
        runtime_path: Path,
        *,
        action: str,
        secret: str | None = None,
    ) -> None:
        launcher = Path(config.distribution_root).resolve() / "bin" / "hypit.mjs"
        if not launcher.is_file():
            raise HypitConfigurationError(
                "Install or select the Hypit distribution before saving its API key"
            )
        command = [
            shutil.which("node") or "node",
            str(launcher),
            "auth",
            action,
            config.endpoint,
            "--runtime",
            str(runtime_path),
        ]
        secret_path: str | None = None
        try:
            if secret is not None:
                with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", delete=False, dir=self._config_path.parent
                ) as handle:
                    handle.write(secret)
                    secret_path = handle.name
                command.extend(["--from", secret_path])
            result = subprocess.run(
                command,
                cwd=config.workspace,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode != 0:
                message = result.stderr.strip() or result.stdout.strip() or "Hypit auth failed"
                raise HypitConfigurationError(message)
        finally:
            if secret_path is not None:
                Path(secret_path).unlink(missing_ok=True)

    def _studio_command(
        self,
        config: HypitConfig,
        runtime_path: Path,
        port: int,
    ) -> list[str]:
        return [
            shutil.which("node") or "node",
            str(Path(config.distribution_root).resolve() / "bin" / "hypit.mjs"),
            "studio",
            "--run",
            str(Path(config.run_file).resolve()),
            "--runtime",
            str(runtime_path),
            "--workspace",
            str(Path(config.workspace).resolve()),
            "--package-root",
            str(Path(config.workspace).resolve()),
            "--port",
            str(port),
        ]

    @staticmethod
    def _free_port(preferred: int) -> int:
        for port in range(preferred, preferred + 40):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
                try:
                    candidate.bind(("127.0.0.1", port))
                    return port
                except OSError:
                    continue
        raise HypitConfigurationError("No local port is available for Hypit Studio")

    @staticmethod
    def _port_is_open(port: int) -> bool:
        try:
            with socket.create_connection(("localhost", port), timeout=0.2):
                return True
        except OSError:
            return False

    def _close_process_resources(self) -> None:
        if self._log_handle is not None:
            self._log_handle.close()
        self._process = None
        self._log_handle = None
        self._url = None

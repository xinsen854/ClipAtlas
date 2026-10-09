import os
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict

from clipatlas.system.pickers import pick
from clipatlas.system.shell import LocalShellService, LocalSystemConfigurationError

router = APIRouter(prefix="/api/v1/system", tags=["system"])


class LogLine(BaseModel):
    level: str
    text: str
    important: bool


class LogsResponse(BaseModel):
    lines: list[LogLine]
    path: str | None


_ERROR_MARKERS = ("ERROR", "Traceback", "Exception", "FAIL", "Error", "失败", "异常", "错误", "无效", "invalid", "timeout", "超时")
_WARN_MARKERS = ("WARN", "Warning", "警告", "重试")


def _log_file_path() -> Path | None:
    candidates = []
    try:
        settings_path = Path(
            os.getenv("CLIPATLAS_SETTINGS_FILE", "./data/config/settings.json")
        ).resolve()
        candidates.append(settings_path.parent.parent / "logs" / "app.log")
    except Exception:
        pass
    candidates.append(Path("./data/logs/app.log").resolve())
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def _classify(line: str) -> tuple[str, bool]:
    if any(marker in line for marker in _ERROR_MARKERS):
        return "ERROR", True
    if any(marker in line for marker in _WARN_MARKERS):
        return "WARN", True
    return "INFO", False


@router.get("/logs", response_model=LogsResponse)
def read_logs(
    lines: int = Query(default=300, ge=10, le=2000),
) -> LogsResponse:
    """读取运行日志（data/logs/app.log）。important=true 表示错误/警告行。"""
    path = _log_file_path()
    if path is None:
        return LogsResponse(lines=[], path=None)
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return LogsResponse(lines=[], path=None)
    raw = text.splitlines()[-lines:]
    result = []
    for row in raw:
        if not row.strip():
            continue
        level, important = _classify(row)
        result.append(LogLine(level=level, text=row[:2000], important=important))
    return LogsResponse(lines=result, path=str(path))


class OpenExportFolderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: UUID


class LocalActionResponse(BaseModel):
    action: str
    path: str


class PickPathResponse(BaseModel):
    path: str | None
    cancelled: bool


def _service(request: Request) -> LocalShellService:
    service = getattr(request.app.state, "local_shell_service", None)
    if not isinstance(service, LocalShellService):
        raise LocalSystemConfigurationError("Local shell service is not configured")
    return service


@router.post("/open-export-folder", response_model=LocalActionResponse)
def open_export_folder(
    request: Request,
    body: OpenExportFolderRequest,
) -> LocalActionResponse:
    path = _service(request).open_generated_export_folder(body.plan_id)
    return LocalActionResponse(action="opened_export_folder", path=str(path))


@router.post("/open-jianying", response_model=LocalActionResponse)
def open_jianying(request: Request) -> LocalActionResponse:
    path = _service(request).launch_jianying()
    return LocalActionResponse(action="launched_jianying", path=str(path))


@router.post("/pick-directory", response_model=PickPathResponse)
def pick_directory(request: Request) -> PickPathResponse:
    """Open the OS-native folder dialog on this machine.

    Only meaningful when the frontend is served by the local backend (the
    portable EXE). Cancelling returns ``cancelled=true`` with a null path.
    """
    if not getattr(request.app.state, "local_picker_enabled", True):
        raise HTTPException(status_code=404, detail="Path picker is not available")
    selected = pick("directory")
    return PickPathResponse(path=selected, cancelled=selected is None)


@router.post("/pick-file", response_model=PickPathResponse)
def pick_file(
    request: Request,
) -> PickPathResponse:
    """Open the OS-native executable file dialog."""
    if not getattr(request.app.state, "local_picker_enabled", True):
        raise HTTPException(status_code=404, detail="Path picker is not available")
    selected = pick("file")
    return PickPathResponse(path=selected, cancelled=selected is None)

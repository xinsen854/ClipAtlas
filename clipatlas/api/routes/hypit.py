from typing import Annotated, Any
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from clipatlas.hypit.service import (
    HypitBuild,
    HypitConfig,
    HypitConfigUpdate,
    HypitConfigurationError,
    HypitConnectionResult,
    HypitInput,
    HypitReference,
    HypitService,
    HypitStatus,
)

router = APIRouter(prefix="/api/v1/hypit", tags=["hypit"])


class HypitBuildRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class HypitBuildTitleUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class HypitBriefUpdate(BaseModel):
    text: str = Field(default="", max_length=20_000)


class HypitOpenOutputResponse(BaseModel):
    action: str
    path: str


class HypitConnectionRequest(BaseModel):
    api_key: str | None = None
    provider_package: str | None = None
    base_url: str | None = None


def _service(request: Request) -> HypitService:
    service = getattr(request.app.state, "hypit_service", None)
    if not isinstance(service, HypitService):
        raise HTTPException(status_code=503, detail="Hypit service is not configured")
    return service


@router.get("/config", response_model=HypitConfig)
def get_config(request: Request) -> HypitConfig:
    return _service(request).config()


@router.put("/config", response_model=HypitConfig)
def update_config(request: Request, body: HypitConfigUpdate) -> HypitConfig:
    try:
        return _service(request).update(body)
    except HypitConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/status", response_model=HypitStatus)
def get_status(request: Request) -> HypitStatus:
    return _service(request).status()


@router.post("/test-connection", response_model=HypitConnectionResult)
def test_connection(request: Request, body: HypitConnectionRequest) -> HypitConnectionResult:
    return _service(request).test_connection(
        body.api_key,
        provider_package=body.provider_package,
        base_url=body.base_url,
    )


@router.post("/start", response_model=HypitStatus)
def start(request: Request) -> HypitStatus:
    try:
        return _service(request).start()
    except HypitConfigurationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/stop", response_model=HypitStatus)
def stop(request: Request) -> HypitStatus:
    return _service(request).stop()


@router.get("/references", response_model=list[HypitReference])
def list_references(request: Request) -> list[HypitReference]:
    return _service(request).references()


@router.post(
    "/references",
    response_model=HypitReference,
    status_code=status.HTTP_201_CREATED,
)
def upload_reference(
    request: Request,
    file: Annotated[UploadFile, File()],
) -> HypitReference:
    try:
        return _service(request).import_reference(
            file.filename or "",
            file.file,
            max_bytes=2 * 1024 * 1024 * 1024,
        )
    except HypitConfigurationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/references/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_reference(request: Request, name: str) -> None:
    try:
        _service(request).delete_reference(name)
    except HypitConfigurationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/inputs", response_model=list[HypitInput])
def list_inputs(request: Request) -> list[HypitInput]:
    return _service(request).inputs()


@router.post("/inputs", response_model=HypitInput, status_code=status.HTTP_201_CREATED)
def upload_input(
    request: Request,
    kind: str,
    file: Annotated[UploadFile, File()],
) -> HypitInput:
    try:
        return _service(request).import_input(
            kind,
            file.filename or "",
            file.file,
            max_bytes=2 * 1024 * 1024 * 1024,
        )
    except HypitConfigurationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/brief")
def get_brief(request: Request) -> dict[str, str]:
    return {"text": _service(request).brief()}


@router.put("/brief")
def update_brief(request: Request, body: HypitBriefUpdate) -> dict[str, str]:
    try:
        _service(request).update_brief(body.text)
    except HypitConfigurationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"text": _service(request).brief()}


@router.post("/builds", response_model=dict[str, Any])
def submit_build(request: Request, body: HypitBuildRequest) -> dict[str, Any]:
    try:
        return _service(request).submit_build(body.title)
    except HypitConfigurationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/builds", response_model=list[HypitBuild])
def list_builds(request: Request) -> list[HypitBuild]:
    try:
        return _service(request).builds()
    except HypitConfigurationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.put("/builds/{build_id}/title", status_code=status.HTTP_204_NO_CONTENT)
def update_build_title(request: Request, build_id: str, body: HypitBuildTitleUpdate) -> None:
    try:
        _service(request).update_build_title(build_id, body.title)
    except HypitConfigurationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/builds/{build_id}/outputs/{output}", response_class=FileResponse)
def export_build_output(request: Request, build_id: str, output: str) -> FileResponse:
    try:
        path = _service(request).export_output(build_id, output)
    except HypitConfigurationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    # Hypit target names (for example ``final.video``) are logical artifact
    # names, not file extensions. Return a usable media filename/type so the
    # browser starts a normal MP4 download instead of treating it as text.
    if output == "final.video":
        return FileResponse(
            path,
            filename="final.mp4",
            media_type="video/mp4",
            headers={"X-Content-Type-Options": "nosniff"},
        )
    return FileResponse(path, filename=path.name, headers={"X-Content-Type-Options": "nosniff"})


@router.post("/builds/{build_id}/outputs/{output}/open", response_model=HypitOpenOutputResponse)
def open_build_output(request: Request, build_id: str, output: str) -> HypitOpenOutputResponse:
    try:
        path = _service(request).export_output(build_id, output)
        config = _service(request).config()
        opened = request.app.state.local_shell_service.open_hypit_output(
            path, Path(config.workspace)
        )
    except HypitConfigurationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return HypitOpenOutputResponse(action="opened_hypit_output", path=str(opened))

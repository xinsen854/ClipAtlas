from typing import cast

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from clipatlas.settings.models import PublicSettings, SettingsPatch
from clipatlas.settings.probe import (
    BailianModelStatus,
    ServiceKind,
    ServiceProbe,
    ServiceProbeRequest,
)
from clipatlas.settings.store import SettingsStore

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


class UpdateSettingsResponse(BaseModel):
    settings: PublicSettings
    restart_required: bool = True


class ProbeSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service: ServiceKind
    provider: str
    api_key: str | None = None
    base_url: str
    model: str
    dimensions: int | None = None


class ProbeConnectionResponse(BaseModel):
    ok: bool
    code: str
    message: str


class ProbeModelsResponse(BaseModel):
    supported: bool
    models: list[str]


class BailianModelDetectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: str | None = None
    base_url: str


class BailianModelDetectionResponse(BaseModel):
    ok: bool
    code: str
    message: str
    models: dict[str, BailianModelStatus]


def _store(request: Request) -> SettingsStore:
    return cast(SettingsStore, request.app.state.settings_store)


def _probe(request: Request) -> ServiceProbe:
    return cast(ServiceProbe, request.app.state.service_probe)


def _effective_api_key(store: SettingsStore, body: ProbeSettingsRequest) -> str | None:
    typed_key = body.api_key.strip() if body.api_key is not None else ""
    if typed_key:
        return typed_key
    if body.service == "video":
        return store.resolve_secret("qwen_api_key")
    if body.service == "embedding":
        return store.resolve_secret("embedding_api_key")
    return store.resolve_secret("speech_api_key")


def _probe_request(store: SettingsStore, body: ProbeSettingsRequest) -> ServiceProbeRequest | None:
    api_key = _effective_api_key(store, body)
    if api_key is None:
        return None
    return ServiceProbeRequest(
        service=body.service,
        provider=body.provider.strip(),
        api_key=api_key,
        base_url=body.base_url.strip(),
        model=body.model.strip(),
        dimensions=body.dimensions,
    )



@router.get("", response_model=PublicSettings)
def get_settings(request: Request) -> PublicSettings:
    return _store(request).public_snapshot()


@router.patch("", response_model=UpdateSettingsResponse)
def update_settings(
    request: Request,
    body: SettingsPatch,
) -> UpdateSettingsResponse:
    store = _store(request)
    if 'library_cache_root' in body.model_fields_set:
        raise HTTPException(status_code=400, detail='请使用缓存目录迁移入口，不能仅修改路径')
    store.update(body)
    return UpdateSettingsResponse(settings=store.public_snapshot())


@router.post("/test-connection", response_model=ProbeConnectionResponse)
async def test_connection(
    request: Request,
    body: ProbeSettingsRequest,
) -> ProbeConnectionResponse:
    probe_request = _probe_request(_store(request), body)
    if probe_request is None:
        return ProbeConnectionResponse(
            ok=False,
            code="missing_api_key",
            message="请先输入或保存 API Key。",
        )

    result = await _probe(request).test_connection(probe_request)
    return ProbeConnectionResponse(ok=result.ok, code=result.code, message=result.message)


@router.post("/models", response_model=ProbeModelsResponse)
async def list_models(
    request: Request,
    body: ProbeSettingsRequest,
) -> ProbeModelsResponse:
    probe_request = _probe_request(_store(request), body)
    if probe_request is None:
        return ProbeModelsResponse(supported=False, models=[])

    result = await _probe(request).list_models(probe_request)
    return ProbeModelsResponse(supported=result.supported, models=result.models)


@router.post("/bailian/models", response_model=BailianModelDetectionResponse)
async def detect_bailian_models(
    request: Request,
    body: BailianModelDetectionRequest,
) -> BailianModelDetectionResponse:
    typed_key = body.api_key.strip() if body.api_key is not None else ""
    api_key = typed_key or _store(request).resolve_secret("bailian_api_key")
    if api_key is None:
        return BailianModelDetectionResponse(
            ok=False,
            code="missing_api_key",
            message="请先输入或保存百炼 API Key。",
            models=ServiceProbe._undetected_bailian_models(),
        )

    result = await _probe(request).detect_bailian_models(
        api_key=api_key,
        base_url=body.base_url.strip(),
    )
    return BailianModelDetectionResponse(
        ok=result.ok,
        code=result.code,
        message=result.message,
        models=result.models,
    )

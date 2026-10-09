import asyncio
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal, Protocol, cast
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from clipatlas.catalog.store import CatalogStore
from clipatlas.concurrency import drain_on_cancel
from clipatlas.domain.models import AnnotationOrigin, SemanticAnnotation
from clipatlas.library.cache_location import CacheMoveResult, move_library_cache
from clipatlas.library.index_progress import LibraryIndexProgressReader, VideoIndexProgress
from clipatlas.library.maintenance import LibraryMaintenance, LibraryResetResult
from clipatlas.library.models import LibraryItem, LibraryItemStatus, LibraryRoot, ScanReport
from clipatlas.library.store import LibraryStore
from clipatlas.library.worker import SequentialLibraryWorker
from clipatlas.settings.store import SettingsStore

router = APIRouter(prefix="/api/v1/library", tags=["library"])


class AddLibraryRootRequest(BaseModel):
    path: str
    recursive: bool = True
    project_id: UUID | None = None


class ResetLibraryRequest(BaseModel):
    confirm: Literal["CLEAR_ALL_LIBRARY_ANALYSIS"]


class CacheLocationRequest(BaseModel):
    path: str = Field(min_length=1)
    confirm: Literal['MOVE_LIBRARY_CACHE']


class CacheLocationResponse(BaseModel):
    path: str
    restart_required: bool
    environment_managed: bool


@router.get('/cache-location', response_model=CacheLocationResponse)
def get_cache_location(request: Request) -> CacheLocationResponse:
    settings = cast(SettingsStore, request.app.state.settings_store)
    return CacheLocationResponse(
        path=str(Path(os.getenv('CLIPATLAS_LIBRARY_CACHE_ROOT', './data/library-cache')).resolve()),
        restart_required=getattr(request.app.state, 'cache_restart_required', False),
        environment_managed=settings.public_snapshot().library_cache_root.source == 'environment',
    )


@router.post('/cache-location', response_model=CacheMoveResult)
async def change_cache_location(request: Request, body: CacheLocationRequest) -> CacheMoveResult:
    worker = cast(SequentialLibraryWorker, request.app.state.library_worker)
    if worker.operation_lock.locked():
        raise HTTPException(status_code=409, detail='请等待当前素材完成后迁移缓存')
    settings = cast(SettingsStore, request.app.state.settings_store)
    maintenance = cast(LibraryMaintenance, request.app.state.library_maintenance)
    supervisor = _processing_supervisor(request)
    was_paused = supervisor.paused
    supervisor.pause()

    async def migrate() -> CacheMoveResult:
        result = await asyncio.to_thread(
            move_library_cache, maintenance.db_path, maintenance.cache_root,
            Path(body.path), settings,
        )
        if result.restart_required:
            settings._inject_compatibility_value('CLIPATLAS_LIBRARY_CACHE_ROOT', result.path, force=True)
            request.app.state.cache_restart_required = True
        return result

    async with worker.operation_lock:
        try:
            return await drain_on_cancel(migrate())
        except (ValueError, OSError, sqlite3.Error) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        finally:
            if not was_paused and not getattr(request.app.state, 'cache_restart_required', False):
                supervisor.resume()


class UpdateAnnotationRequest(BaseModel):
    description: str | None = Field(default=None, min_length=1)
    characters: list[str] | None = None
    actions: list[str] | None = None
    scene: list[str] | None = None
    emotions: list[str] | None = None
    objects: list[str] | None = None
    ocr: list[str] | None = None
    shot_type: str | None = None
    camera_motion: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    locked: bool | None = None


class AnnotationCorrectionResponse(BaseModel):
    annotation: SemanticAnnotation
    embedding_updated: bool


class LibraryProcessingState(BaseModel):
    available: bool
    paused: bool


class LibraryItemDetailResponse(LibraryItem):
    prepared_video_id: UUID | None = None
    index_progress: VideoIndexProgress | None = None
    processing_stage: Literal["visual", "asr", "ocr", "finalizing"] | None = None
    processing_stages: list[Literal["visual", "asr", "ocr"]] = Field(default_factory=list)
    progress_updated_at: datetime | None = None


class LibraryScannerLike(Protocol):
    def scan_all(self) -> ScanReport: ...


class LibraryProcessingSupervisorLike(Protocol):
    @property
    def processing_available(self) -> bool: ...

    @property
    def paused(self) -> bool: ...

    def pause(self) -> None: ...

    def resume(self) -> bool: ...


class LibraryExplicitWorkerLike(Protocol):
    async def parse_item(self, item_id: UUID) -> bool: ...

    async def reparse_item(self, item_id: UUID) -> bool: ...


class SemanticIndexerLike(Protocol):
    async def index_segment(self, segment_id: UUID) -> bool: ...


def _store(request: Request) -> LibraryStore:
    store = request.app.state.library_store
    if not isinstance(store, LibraryStore):
        raise TypeError("library store is not configured")
    return store


def _catalog(request: Request) -> CatalogStore:
    catalog = getattr(request.app.state, "library_catalog", None)
    if not isinstance(catalog, CatalogStore):
        raise TypeError("library catalog is not configured")
    return catalog


def _scanner(request: Request) -> LibraryScannerLike:
    scanner = request.app.state.library_scanner
    if not hasattr(scanner, "scan_all"):
        raise TypeError("library scanner is not configured")
    return cast(LibraryScannerLike, scanner)


def _processing_supervisor(request: Request) -> LibraryProcessingSupervisorLike:
    supervisor = getattr(request.app.state, "library_supervisor", None)
    required = ("processing_available", "paused", "pause", "resume")
    if supervisor is None or not all(hasattr(supervisor, name) for name in required):
        raise TypeError("library supervisor is not configured")
    return cast(LibraryProcessingSupervisorLike, supervisor)


def _explicit_worker(request: Request) -> LibraryExplicitWorkerLike:
    worker = getattr(request.app.state, "library_worker", None)
    required = ("parse_item", "reparse_item")
    if worker is None or not all(hasattr(worker, name) for name in required):
        raise TypeError("library worker is not configured")
    return cast(LibraryExplicitWorkerLike, worker)


def _processing_state(supervisor: LibraryProcessingSupervisorLike) -> LibraryProcessingState:
    return LibraryProcessingState(
        available=supervisor.processing_available,
        paused=supervisor.paused,
    )


def _semantic_indexer(request: Request) -> SemanticIndexerLike:
    indexer = getattr(request.app.state, "semantic_indexer", None)
    if indexer is None or not hasattr(indexer, "index_segment"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="semantic indexer is not configured",
        )
    return cast(SemanticIndexerLike, indexer)


def _item_or_404(store: LibraryStore, item_id: UUID) -> LibraryItem:
    item = store.get_item(item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="library item not found",
        )
    return item


def _require_processing_available(supervisor: LibraryProcessingSupervisorLike) -> None:
    if not supervisor.processing_available:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="video understanding provider is not configured",
        )


def _effective_annotation_or_404(catalog: CatalogStore, segment_id: UUID) -> SemanticAnnotation:
    annotation = catalog.get_effective_annotation(segment_id)
    if annotation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="segment annotation not found",
        )
    return annotation


@router.post("/roots", response_model=LibraryRoot, status_code=status.HTTP_201_CREATED)
def add_root(request: Request, payload: AddLibraryRootRequest) -> LibraryRoot:
    path = Path(payload.path).expanduser().resolve(strict=False)
    if not path.is_dir():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="library root must be an existing directory",
        )
    return _store(request).add_root(
        path, recursive=payload.recursive, project_id=payload.project_id,
    )


@router.get("/roots", response_model=list[LibraryRoot])
def list_roots(
    request: Request,
    project_id: UUID | None = None,
) -> list[LibraryRoot]:
    return _store(request).list_roots(project_id=project_id)


@router.get("/items", response_model=list[LibraryItem])
def list_items(
    request: Request,
    root_id: UUID | None = None,
    item_status: Annotated[LibraryItemStatus | None, Query(alias="status")] = None,
    project_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[LibraryItem]:
    return _store(request).list_items(
        root_id=root_id,
        status=item_status,
        limit=limit,
        offset=offset,
        project_id=project_id,
    )


@router.get("/items/{item_id}", response_model=LibraryItemDetailResponse)
def get_item(request: Request, item_id: UUID) -> LibraryItemDetailResponse:
    item = _item_or_404(_store(request), item_id)
    result = LibraryItemDetailResponse(**item.model_dump())
    reader = getattr(request.app.state, "library_index_progress", None)
    if not isinstance(reader, LibraryIndexProgressReader):
        return result
    prepared = reader.get_for_item(item.id, item.fingerprint)
    if prepared is None:
        return result
    result.prepared_video_id = prepared.video_id
    result.index_progress = prepared.progress
    result.progress_updated_at = prepared.updated_at
    if item.status in {
        LibraryItemStatus.PROBING, LibraryItemStatus.SCENE_DETECTION,
        LibraryItemStatus.FRAME_EXTRACTION,
    }:
        sources = [
            ("visual", prepared.progress.visual), ("asr", prepared.progress.asr),
            ("ocr", prepared.progress.ocr),
        ]
        active = next((name for name, progress in sources if progress.processing > 0), None)
        result.processing_stages = [
            cast(Literal["visual", "asr", "ocr"], name)
            for name, progress in sources if progress.processing > 0
        ]
        pending = next((name for name, progress in sources if progress.enabled and
                        progress.applicable and progress.completed < progress.total), None)
        result.processing_stage = cast(
            Literal["visual", "asr", "ocr", "finalizing"], active or pending or "finalizing",
        )
    return result


@router.get("/summary", response_model=dict[str, int])
def summary(request: Request, project_id: UUID | None = None) -> dict[str, int]:
    counts = _store(request).counts_by_status(project_id=project_id)
    return {item_status.value: count for item_status, count in counts.items()}


@router.post("/scan", response_model=ScanReport)
def scan(request: Request) -> ScanReport:
    return _scanner(request).scan_all()


@router.get("/processing", response_model=LibraryProcessingState)
def processing_status(request: Request) -> LibraryProcessingState:
    return _processing_state(_processing_supervisor(request))


@router.post("/reset-analysis", response_model=LibraryResetResult)
async def reset_analysis(request: Request, body: ResetLibraryRequest) -> LibraryResetResult:
    worker = cast(SequentialLibraryWorker, request.app.state.library_worker)
    if worker.operation_lock.locked():
        raise HTTPException(status_code=409, detail="请等待当前素材解析完成后再清空")
    _processing_supervisor(request).pause()
    maintenance = cast(LibraryMaintenance, request.app.state.library_maintenance)
    async with worker.operation_lock:
        try:
            return await asyncio.to_thread(maintenance.reset_analysis)
        except (ValueError, OSError, sqlite3.Error) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc


class LibrarySupplementResult(BaseModel):
    failed: int = 0
    interrupted: int = 0
    incomplete: int = 0
    total: int = 0


@router.post("/supplement", response_model=LibrarySupplementResult)
def supplement(request: Request) -> LibrarySupplementResult:
    """增补解析：失败/中断/缺数据的素材放回队列，后台继续增量补全。"""
    worker = cast(SequentialLibraryWorker, request.app.state.library_worker)
    if worker.operation_lock.locked():
        raise HTTPException(status_code=409, detail="请等待当前素材解析完成后再增补")
    _processing_supervisor(request).pause()
    try:
        summary = worker.supplement_candidates()
    finally:
        _processing_supervisor(request).resume()
    return LibrarySupplementResult(**summary)


@router.post("/processing/pause", response_model=LibraryProcessingState)
def pause_processing(request: Request) -> LibraryProcessingState:
    supervisor = _processing_supervisor(request)
    supervisor.pause()
    return _processing_state(supervisor)


@router.post("/processing/resume", response_model=LibraryProcessingState)
def resume_processing(request: Request) -> LibraryProcessingState:
    supervisor = _processing_supervisor(request)
    if not supervisor.resume():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="video understanding provider is not configured",
        )
    return _processing_state(supervisor)


@router.post("/items/{item_id}/parse", response_model=LibraryItem)
async def parse_item(request: Request, item_id: UUID) -> LibraryItem:
    store = _store(request)
    _item_or_404(store, item_id)
    _require_processing_available(_processing_supervisor(request))
    if not await _explicit_worker(request).parse_item(item_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="library item is not eligible for explicit parse",
        )
    return _item_or_404(store, item_id)


@router.post("/items/{item_id}/reparse", response_model=LibraryItem)
async def reparse_item(request: Request, item_id: UUID) -> LibraryItem:
    store = _store(request)
    _item_or_404(store, item_id)
    _require_processing_available(_processing_supervisor(request))
    if not await _explicit_worker(request).reparse_item(item_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="library item is not eligible for explicit reparse",
        )
    return _item_or_404(store, item_id)


@router.post("/items/{item_id}/retry", response_model=dict[str, str])
def retry_item(request: Request, item_id: UUID) -> dict[str, str]:
    if not _store(request).retry(item_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="library item is not in FAILED state",
        )
    return {"status": LibraryItemStatus.QUEUED.value}


@router.get("/segments/{segment_id}/annotation", response_model=SemanticAnnotation)
def get_effective_annotation(request: Request, segment_id: UUID) -> SemanticAnnotation:
    return _effective_annotation_or_404(_catalog(request), segment_id)


@router.patch(
    "/segments/{segment_id}/annotation",
    response_model=AnnotationCorrectionResponse,
)
async def correct_annotation(
    request: Request,
    segment_id: UUID,
    payload: UpdateAnnotationRequest,
) -> AnnotationCorrectionResponse:
    catalog = _catalog(request)
    current = _effective_annotation_or_404(catalog, segment_id)
    indexer = _semantic_indexer(request)

    values = current.model_dump(
        exclude={
            "id",
            "origin",
            "provider",
            "model",
            "verified",
            "revision",
            "created_at",
        }
    )
    values.update(payload.model_dump(exclude_unset=True))
    corrected = SemanticAnnotation(
        **values,
        origin=AnnotationOrigin.HUMAN,
        provider=None,
        model=None,
        verified=True,
        revision=current.revision + 1,
    )
    catalog.save_annotation(corrected)
    embedding_updated = await indexer.index_segment(segment_id)
    return AnnotationCorrectionResponse(
        annotation=corrected,
        embedding_updated=embedding_updated,
    )

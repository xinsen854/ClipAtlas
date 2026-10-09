import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from hashlib import file_digest, sha256
from typing import Annotated, Literal, cast
from uuid import UUID, uuid5

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field

from clipatlas.api.routes.projects import _project_or_404
from clipatlas.api.routes.projects import _store as _projects
from clipatlas.api.routes.rough_cut import _planner
from clipatlas.api.routes.rough_cut import _store as _plans
from clipatlas.api.routes.speech import (
    NarrationTrackResponse,
    _imported_service,
    _store,
    _track_response,
    _uploaded_audio,
)
from clipatlas.roughcut.models import RoughCutPlan
from clipatlas.roughcut.batch_assignment import append_plan_usage, batch_assignment_order
from clipatlas.speech.batches import (
    BatchAudioFile,
    BatchEntry,
    BatchMatch,
    BatchSummary,
    ExportRatio,
    NarrationBatch,
    match_batch_audio,
    parse_batch_markdown,
)
from clipatlas.speech.service import split_narration_units
from clipatlas.director.requirements import parse_script_visual_requirements

router = APIRouter(prefix="/api/v1/projects/{project_id}/narration-batches", tags=["narration-batches"])
logger = logging.getLogger(__name__)


class PreviewBatchRequest(BaseModel):
    markdown: str = Field(min_length=1, max_length=2_000_000)
    files: list[BatchAudioFile] = Field(default_factory=list, max_length=100)


class BatchAssignment(BaseModel):
    entry_id: str
    audio_index: int = Field(ge=0, lt=100)


class CreateBatchRequest(PreviewBatchRequest):
    name: str = Field(min_length=1, max_length=200)
    assignments: list[BatchAssignment] = Field(min_length=1, max_length=100)
    top_k: int = Field(default=12, ge=1, le=100)
    export_ratio: ExportRatio = ExportRatio.LANDSCAPE_16_9
    confirm: Literal["MATCHES_CONFIRMED"]


class GenerateBatchPlanRequest(BaseModel):
    confirm: Literal["GENERATE_ROUGH_CUT"]


class GenerateBatchPlansRequest(BaseModel):
    confirm: Literal["GENERATE_BATCH_ROUGH_CUT"]


def _batch(request: Request, project_id: UUID, batch_id: UUID) -> NarrationBatch:
    _project_or_404(_projects(request), project_id)
    batch = _store(request).get_batch(batch_id)
    if batch is None or batch.project_id != project_id:
        raise HTTPException(status_code=404, detail="batch not found in this project")
    return batch


def _entry(batch: NarrationBatch, entry_id: str) -> BatchEntry:
    for entry in batch.entries:
        if entry.id == entry_id:
            return entry
    raise HTTPException(status_code=404, detail="batch entry not found")


@asynccontextmanager
async def _operation(request: Request) -> AsyncIterator[None]:
    lock = cast(asyncio.Lock, request.app.state.narration_batch_lock)
    if lock.locked():
        raise HTTPException(status_code=409, detail="有批量条目正在处理，请等当前条目完成")
    async with lock:
        yield


@router.post("/preview", response_model=list[BatchMatch])
def preview_batch(request: Request, project_id: UUID, body: PreviewBatchRequest) -> list[BatchMatch]:
    _project_or_404(_projects(request), project_id)
    try:
        return match_batch_audio(parse_batch_markdown(body.markdown), body.files)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("", response_model=NarrationBatch, status_code=201)
async def create_batch(request: Request, project_id: UUID, body: CreateBatchRequest) -> NarrationBatch:
    _project_or_404(_projects(request), project_id)
    try:
        scripts = parse_batch_markdown(body.markdown)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    mapping = {item.entry_id: item.audio_index for item in body.assignments}
    if (
        len(mapping) != len(body.assignments)
        or set(mapping) != {item.id for item in scripts}
        or len(set(mapping.values())) != len(mapping)
        or any(index >= len(body.files) for index in mapping.values())
    ):
        raise HTTPException(status_code=422, detail="每条文案必须匹配一个不同的旁白文件")
    descriptors = [(body.files[i].name, body.files[i].size) for i in mapping.values()]
    if len(set(descriptors)) != len(descriptors):
        raise HTTPException(status_code=422, detail="存在同名同大小的旁白文件，请先重命名以便确认和续传")
    batch = NarrationBatch(project_id=project_id, name=body.name, top_k=body.top_k,
                           export_ratio=body.export_ratio.value, entries=[
        BatchEntry(**script.model_dump(), audio_name=body.files[mapping[script.id]].name,
                   audio_size=body.files[mapping[script.id]].size)
        for script in scripts
    ])
    _store(request).save_batch(batch)
    query_service = getattr(request.app.state, "requirement_query_embedding_service", None)
    if query_service is not None:
        try:
            requirements = [
                requirement
                for entry in batch.entries
                for requirement in parse_script_visual_requirements(entry.text)
            ]
            await query_service.prepare(requirements)
        except Exception as exc:  # noqa: BLE001 - text recall remains available
            logger.warning("batch query-vector preparation unavailable: %s", str(exc)[:500])
    return batch


@router.get("", response_model=list[BatchSummary])
def list_batches(
    request: Request, project_id: UUID,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[BatchSummary]:
    _project_or_404(_projects(request), project_id)
    return _store(request).list_batches(project_id, limit=limit, offset=offset)


@router.get("/{batch_id}", response_model=NarrationBatch)
def get_batch(request: Request, project_id: UUID, batch_id: UUID) -> NarrationBatch:
    return _batch(request, project_id, batch_id)


@router.post("/{batch_id}/entries/{entry_id}/audio", response_model=NarrationTrackResponse)
async def import_batch_audio(
    request: Request, project_id: UUID, batch_id: UUID, entry_id: str,
    file: Annotated[UploadFile, File()],
) -> NarrationTrackResponse:
    async with _operation(request):
        batch = _batch(request, project_id, batch_id)
        entry = _entry(batch, entry_id)
        if file.filename != entry.audio_name:
            raise HTTPException(status_code=422, detail="音频文件名与已确认的匹配不一致")
        store = _store(request)
        track_id = uuid5(batch.id, "audio:" + entry.id)
        try:
            async with _uploaded_audio(request, file) as path:
                if path.stat().st_size != entry.audio_size:
                    raise HTTPException(status_code=422, detail="音频大小已改变，请重新建立匹配")
                with path.open("rb") as audio_file:
                    digest = file_digest(audio_file, "sha256").hexdigest()
                if entry.audio_sha256 is not None and entry.audio_sha256 != digest:
                    raise HTTPException(status_code=422, detail="音频内容已改变，请使用原文件或新建批次")
                if entry.audio_sha256 is None:
                    entry.audio_sha256 = digest
                    store.save_batch(batch)
                track = store.get_track(track_id)
                if track is not None and (
                    track.project_id != project_id
                    or track.script_hash != sha256(entry.text.encode()).hexdigest()
                ):
                    raise HTTPException(status_code=409, detail="已保存旁白与该批次条目不一致")
                complete_units = track is not None and [
                    unit.text for unit in store.list_units(track.id)
                ] == split_narration_units(entry.text)
                if not complete_units:
                    track = await _imported_service(request).import_track(
                        project_id, path, entry.text, activate=False, track_id=track_id,
                    )
                assert track is not None
                if track.project_id != project_id or track.script_hash != sha256(entry.text.encode()).hexdigest():
                    raise HTTPException(status_code=409, detail="已保存旁白与该批次条目不一致")
            entry.narration_track_id = track.id
            entry.duration_ms = track.duration_ms
            entry.last_error = None
            store.save_batch(batch)
            return _track_response(store, track)
        except Exception as exc:
            entry.last_error = str(exc)[:2000]
            store.save_batch(batch)
            raise


@router.post("/{batch_id}/entries/{entry_id}/plan", response_model=RoughCutPlan)
async def generate_batch_plan(
    request: Request, project_id: UUID, batch_id: UUID, entry_id: str,
    body: GenerateBatchPlanRequest,
) -> RoughCutPlan:
    async with _operation(request):
        batch = _batch(request, project_id, batch_id)
        entry = _entry(batch, entry_id)
        if entry.narration_track_id is None:
            raise HTTPException(status_code=409, detail="请先导入该条文案的旁白")
        plan_id = uuid5(batch.id, "plan:" + entry.id)
        try:
            plan = _plans(request).get_plan(plan_id)
            if plan is None:
                # 批次级去重：聚合本批次其它已生成成片用掉的片段，滚动窗口内
                # 避让；S 级稀缺画面轻避让，泛化画面自动错开。
                batch_usage: dict[str, list[tuple[int, int, int]]] = {}
                for idx, other in enumerate(batch.entries):
                    if other.id == entry_id or not other.plan_id:
                        continue
                    other_plan = _plans(request).get_plan(other.plan_id)
                    if other_plan is None:
                        continue
                    for clip in other_plan.clips:
                        batch_usage.setdefault(str(clip.video_id), []).append(
                            (clip.source_in_ms, clip.source_out_ms, idx)
                        )
                batch_index = next(
                    (i for i, e in enumerate(batch.entries) if e.id == entry_id), 0
                )
                plan = await _planner(request).create_plan(
                    project_id, top_k=batch.top_k, narration_track_id=entry.narration_track_id,
                    script_text=entry.text,
                    activate=False, plan_id=plan_id,
                    batch_usage=batch_usage, batch_index=batch_index,
                )
            source = _store(request).get_track(entry.narration_track_id)
            aligned = _store(request).get_track(plan.narration_track_id)
            same_narration = plan.narration_track_id == entry.narration_track_id or (
                source is not None and aligned is not None
                and aligned.project_id == project_id
                and aligned.alignment_source_id == source.id
                and aligned.script_hash == source.script_hash and aligned.audio_uri == source.audio_uri
            )
            if plan.project_id != project_id or not same_narration:
                raise HTTPException(status_code=409, detail="粗剪结果与批次旁白不一致")
            entry.plan_id = plan.id
            entry.last_error = None
            _store(request).save_batch(batch)
            return plan
        except Exception as exc:
            entry.last_error = str(exc)[:2000]
            _store(request).save_batch(batch)
            raise


@router.post("/{batch_id}/plans", response_model=list[RoughCutPlan])
async def generate_batch_plans(
    request: Request, project_id: UUID, batch_id: UUID,
    body: GenerateBatchPlansRequest,
) -> list[RoughCutPlan]:
    """Prepare every entry first, then allocate the batch deterministically."""
    async with _operation(request):
        batch = _batch(request, project_id, batch_id)
        planner = _planner(request)
        provisional: list[RoughCutPlan] = []
        plan_ids: list[UUID] = []
        batch_revision_key = batch.updated_at.isoformat()
        for entry in batch.entries:
            if entry.narration_track_id is None:
                raise HTTPException(status_code=409, detail="请先导入批次内全部旁白")
            # A unified allocation is a new plan revision; do not overwrite the
            # stable per-entry plan produced by the legacy endpoint.
            plan_id = uuid5(batch.id, f"batch-plan:{entry.id}:{batch_revision_key}")
            plan_ids.append(plan_id)
            provisional.append(await planner.create_plan(
                project_id,
                top_k=batch.top_k,
                narration_track_id=entry.narration_track_id,
                script_text=entry.text,
                activate=False,
                plan_id=plan_id,
                persist=False,
            ))

        order = batch_assignment_order(provisional)
        batch.assignment_revision += 1
        batch.assignment_order = [batch.entries[index].id for index in order]
        batch.candidate_snapshot = {
            batch.entries[index].id: [
                item for beat in provisional[index].beats
                for item in (beat.retrieval_intent.get("candidate_matrix") or [])
                if isinstance(item, dict)
            ]
            for index in range(len(provisional))
        }
        usage: dict[str, list[tuple[int, int, int]]] = {}
        final: list[RoughCutPlan | None] = [None] * len(batch.entries)
        for allocation_rank, batch_index in enumerate(order):
            entry = batch.entries[batch_index]
            plan = await planner.create_plan(
                project_id,
                top_k=batch.top_k,
                narration_track_id=entry.narration_track_id,
                script_text=entry.text,
                activate=False,
                plan_id=plan_ids[batch_index],
                batch_usage=usage,
                batch_index=allocation_rank,
            )
            final[batch_index] = plan
            append_plan_usage(usage, plan, batch_index=allocation_rank)
            entry.plan_id = plan.id
            entry.last_error = None
        _store(request).save_batch(batch)
        return [plan for plan in final if plan is not None]

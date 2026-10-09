from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Body, HTTPException, Request

from clipatlas.integrations.finecut.candidate_bridge import candidate_list_from_beat
from clipatlas.integrations.finecut.media_bridge import media_reference
from clipatlas.integrations.finecut.narration_bridge import narration_reference
from clipatlas.integrations.finecut.roughcut_bridge import timeline_from_roughcut
from clipatlas.roughcut.models import RoughCutPlan, ScriptBeat
from clipatlas.speech.models import NarrationTrack
from finecut.editing import (
    delete_clip,
    replace_clip,
    split_clip,
    trim_clip,
    update_clip_properties,
)
from finecut.models import (
    CandidateItem,
    CandidateList,
    MediaReference,
    NarrationReference,
    TimelineDocument,
)

router = APIRouter(prefix="/api/v1/finecut", tags=["finecut"])


def _plan(request: Request, plan_id: UUID) -> RoughCutPlan:
    plan = request.app.state.rough_cut_store.get_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="FineCut source plan not found")
    return plan


def _beat(plan: RoughCutPlan, context_id: UUID) -> ScriptBeat:
    for beat in plan.beats:
        if beat.id == context_id:
            return beat
    raise HTTPException(status_code=404, detail="FineCut narration context not found")


def _media(request: Request, media_id: UUID) -> MediaReference:
    offset = 0
    page_size = 200
    while True:
        items = request.app.state.library_store.list_items(limit=page_size, offset=offset)
        for item in items:
            if item.video_id != media_id:
                continue
            reference = media_reference(item)
            if reference is None:
                raise HTTPException(status_code=404, detail="FineCut media unavailable")
            return reference
        if len(items) < page_size:
            break
        offset += len(items)
    raise HTTPException(status_code=404, detail="FineCut media not found")


def _same_source_path(source_path: str, source_id: str) -> bool:
    if source_path == source_id:
        return True
    try:
        return Path(source_path).expanduser().resolve(strict=False) == Path(source_id).expanduser().resolve(
            strict=False
        )
    except OSError:
        return False


def _resolve_source_media(
    request: Request,
    plan: RoughCutPlan,
    source_id: str,
) -> MediaReference:
    candidate_ids: set[UUID] = {
        clip.video_id
        for clip in plan.clips
        if str(clip.segment_id) == source_id
    }

    offset = 0
    page_size = 200
    while True:
        items = request.app.state.library_store.list_items(limit=page_size, offset=offset)
        for item in items:
            if item.video_id is None:
                continue
            if str(item.video_id) == source_id or _same_source_path(item.source_path, source_id):
                candidate_ids.add(item.video_id)
        if len(items) < page_size:
            break
        offset += len(items)

    if not candidate_ids:
        raise HTTPException(status_code=404, detail="FineCut media source unresolved")
    if len(candidate_ids) > 1:
        raise HTTPException(status_code=409, detail="FineCut media source is ambiguous")
    return _media(request, next(iter(candidate_ids)))


@router.get("/plans/{plan_id}/timeline", response_model=TimelineDocument)
def get_finecut_timeline(request: Request, plan_id: UUID) -> TimelineDocument:
    plan = _plan(request, plan_id)
    saved = request.app.state.finecut_timeline_store.get(plan.project_id, plan.id)
    return saved if saved is not None else timeline_from_roughcut(plan)


@router.put("/plans/{plan_id}/timeline", response_model=TimelineDocument)
def put_finecut_timeline(
    request: Request,
    plan_id: UUID,
    document: TimelineDocument,
) -> TimelineDocument:
    plan = _plan(request, plan_id)
    if document.source_plan_id != plan.id or document.project_id != plan.project_id:
        raise HTTPException(status_code=400, detail="FineCut timeline identity mismatch")
    request.app.state.finecut_timeline_store.save(document)
    return document


@router.post("/edit/replace", response_model=TimelineDocument)
def replace_finecut_clip(
    document: TimelineDocument,
    candidate: CandidateItem,
    media: MediaReference,
    target_clip_id: UUID = Body(),
) -> TimelineDocument:
    try:
        return replace_clip(document, target_clip_id, candidate, media)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/edit/trim", response_model=TimelineDocument)
def trim_finecut_clip(
    document: TimelineDocument,
    target_clip_id: UUID = Body(),
    edge: str = Body(),
    delta_ms: int = Body(),
) -> TimelineDocument:
    try:
        return trim_clip(document, target_clip_id, edge=edge, delta_ms=delta_ms)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/edit/split", response_model=TimelineDocument)
def split_finecut_clip(
    document: TimelineDocument,
    target_clip_id: UUID = Body(),
    split_timeline_ms: int = Body(),
) -> TimelineDocument:
    try:
        return split_clip(document, target_clip_id, split_timeline_ms=split_timeline_ms)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/edit/delete", response_model=TimelineDocument)
def delete_finecut_clip(
    document: TimelineDocument,
    target_clip_id: UUID = Body(),
) -> TimelineDocument:
    try:
        return delete_clip(document, target_clip_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/edit/properties", response_model=TimelineDocument)
def update_finecut_clip_properties(
    document: TimelineDocument,
    target_clip_id: UUID = Body(),
    opacity: float | None = Body(default=None),
    volume: float | None = Body(default=None),
    transform: dict[str, float] | None = Body(default=None),
) -> TimelineDocument:
    try:
        return update_clip_properties(
            document,
            target_clip_id,
            opacity=opacity,
            volume=volume,
            transform=transform,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/media/{media_id}", response_model=MediaReference)
def get_finecut_media(request: Request, media_id: UUID) -> MediaReference:
    return _media(request, media_id)


@router.get(
    "/plans/{plan_id}/media-resolution/{source_id:path}",
    response_model=MediaReference,
)
def resolve_finecut_media(
    request: Request,
    plan_id: UUID,
    source_id: str,
) -> MediaReference:
    return _resolve_source_media(request, _plan(request, plan_id), source_id)


@router.get("/plans/{plan_id}/narration", response_model=NarrationReference)
def get_finecut_narration(request: Request, plan_id: UUID) -> NarrationReference:
    plan = _plan(request, plan_id)
    track: NarrationTrack | None = request.app.state.narration_store.get_track(
        plan.narration_track_id
    )
    if track is None:
        raise HTTPException(status_code=404, detail="FineCut narration track not found")
    return narration_reference(track, plan.beats, include_visual_only=True)


@router.get(
    "/plans/{plan_id}/candidates/{context_id}",
    response_model=CandidateList,
)
def get_finecut_candidates(
    request: Request,
    plan_id: UUID,
    context_id: UUID,
) -> CandidateList:
    plan = _plan(request, plan_id)
    return candidate_list_from_beat(_beat(plan, context_id))

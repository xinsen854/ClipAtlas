"""Read-only presentation of persisted indexes. No model calls or materialization."""

import json
import mimetypes
import os
from pathlib import Path
from typing import Annotated, Literal, cast
from urllib.parse import urlparse
from urllib.request import url2pathname
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from clipatlas.api.routes.videos import _catalog, _video_or_404
from clipatlas.asr.models import ASRChunkRecord
from clipatlas.asr.store import ASRStore
from clipatlas.catalog.store import CatalogStore, VisualChunkSummary
from clipatlas.domain.models import SemanticSpan
from clipatlas.ocr.models import OCRSampleRecord
from clipatlas.ocr.store import OCRStore, normalize_ocr_text

router = APIRouter(prefix="/api/v1/videos", tags=["videos"])
IndexSource = Literal["visual", "summary", "asr", "ocr"]


def readable_ocr_text(raw: str) -> str:
    """Presentation only: unwrap vendor JSON, then reuse existing HTML normalization."""
    text = raw.strip()
    if text.startswith("```") and text.endswith("```"):
        text = "\n".join(text.splitlines()[1:-1]).strip()
    try:
        payload = json.loads(text)
    except (ValueError, RecursionError):
        payload = None
    if isinstance(payload, dict) and isinstance(payload.get("text"), str):
        text = payload["text"]
    elif isinstance(payload, list) and all(
        isinstance(item, dict) and isinstance(item.get("text"), str) for item in payload
    ):
        text = "\n".join(item["text"] for item in payload)
    return "\n".join(normalize_ocr_text(line) for line in text.splitlines()).strip()


class OCRSampleResult(OCRSampleRecord):
    readable_text: str


class SemanticSpanResult(BaseModel):
    start_ms: int
    end_ms: int
    summary: str
    subjects: list[str]
    actions: list[str]
    scenes: list[str]
    presentation_type: str | None
    pollution_level: Literal["clean", "text_heavy", "blocked"]

    @classmethod
    def from_span(cls, span: SemanticSpan) -> "SemanticSpanResult":
        return cls(**span.model_dump(include=set(cls.model_fields)))


class IndexResultsPage(BaseModel):
    source: IndexSource
    items: list[VisualChunkSummary | SemanticSpanResult | ASRChunkRecord | OCRSampleResult]
    limit: int
    offset: int
    has_more: bool


def _cached_frame(catalog: CatalogStore, video_id: UUID, timestamp_ms: int) -> Path | None:
    uri = catalog.get_video_frame_uri(video_id, timestamp_ms)
    if uri is None:
        return None
    parsed = urlparse(uri)
    if parsed.scheme != "file" or parsed.netloc not in ("", "localhost"):
        return None
    root = Path(os.getenv("CLIPATLAS_LIBRARY_CACHE_ROOT", "./data/library-cache")).resolve()
    try:
        path = Path(url2pathname(parsed.path)).resolve()
        if (
            path.is_relative_to(root)
            and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
            and path.is_file()
        ):
            return path
    except (OSError, ValueError):
        pass
    return None


@router.get("/{video_id}/index-thumbnail", response_class=FileResponse)
def get_index_thumbnail(
    request: Request, video_id: UUID, timestamp_ms: Annotated[int, Query(ge=0)],
) -> FileResponse:
    catalog = _catalog(request)
    _video_or_404(catalog, video_id)
    path = _cached_frame(catalog, video_id, timestamp_ms)
    if path is None:
        raise HTTPException(status_code=404, detail="cached frame not found")
    return FileResponse(path, headers={"X-Content-Type-Options": "nosniff"})


@router.get("/{video_id}/source-media", response_class=FileResponse)
def get_source_media(request: Request, video_id: UUID) -> FileResponse:
    """Serve only a catalogued video; Starlette handles HTTP Range for seeking."""
    video = _video_or_404(_catalog(request), video_id)
    parsed = urlparse(video.source_uri)
    if parsed.scheme != "file" or parsed.netloc not in ("", "localhost"):
        raise HTTPException(status_code=404, detail="local source video not available")
    path = Path(url2pathname(parsed.path)).resolve()
    if path.suffix.lower() not in {".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi"}:
        raise HTTPException(status_code=404, detail="unsupported source media type")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="source video missing or moved")
    media_type = "video/mp4" if path.suffix.lower() in {".mp4", ".m4v"} else (
        mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    )
    return FileResponse(path, media_type=media_type,
                        headers={"X-Content-Type-Options": "nosniff"})


@router.get("/{video_id}/index-results/{source}", response_model=IndexResultsPage)
def get_index_results(
    request: Request,
    video_id: UUID,
    source: IndexSource,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> IndexResultsPage:
    catalog = _catalog(request)
    _video_or_404(catalog, video_id)
    items: list[VisualChunkSummary | SemanticSpanResult | ASRChunkRecord | OCRSampleResult]
    if source == "visual":
        chunks = catalog.list_visual_chunk_summaries(video_id, limit=limit + 1, offset=offset)
        for chunk in chunks[:limit]:
            timestamp_ms = (chunk.start_ms + chunk.end_ms) // 2
            if _cached_frame(catalog, video_id, timestamp_ms) is not None:
                chunk.thumbnail_url = (
                    f"/api/v1/videos/{video_id}/index-thumbnail?timestamp_ms={timestamp_ms}"
                )
        items = list(chunks)
    elif source == "summary":
        items = [
            SemanticSpanResult.from_span(span)
            for span in catalog.list_semantic_spans(video_id, limit=limit + 1, offset=offset)
        ]
    elif source == "asr":
        asr = cast(ASRStore, request.app.state.library_asr_store)
        items = list(asr.list_asr_chunks(video_id, limit=limit + 1, offset=offset))
    else:
        ocr = cast(OCRStore, request.app.state.library_ocr_store)
        items = [
            OCRSampleResult(**record.model_dump(), readable_text=readable_ocr_text(record.text))
            for record in ocr.list_samples(video_id, limit=limit + 1, offset=offset)
        ]
    return IndexResultsPage(
        source=source, items=items[:limit], limit=limit, offset=offset, has_more=len(items) > limit,
    )

"""Standalone read-only ClipAtlas library API used by the LAN companion."""
from __future__ import annotations

import mimetypes
import os
import sqlite3
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlparse
from urllib.request import url2pathname
from uuid import UUID

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse

from clipatlas.api.errors import register_error_handlers
from clipatlas.catalog.store import CatalogStore
from clipatlas.asr.store import ASRStore
from clipatlas.embeddings.qwen import QwenTextEmbeddingProvider
from clipatlas.embeddings.qwen_vl import QwenVLVideoEmbeddingProvider
from clipatlas.ocr.store import OCRStore
from clipatlas.projects.store import ProjectStore
from clipatlas.retrieval.hybrid import HybridSearchService
from clipatlas.retrieval.search import CoarseVideoSearchService, SemanticSearchService
from clipatlas.retrieval.video_profiles import get_video_index_profile
from clipatlas.settings.bailian import derive_bailian_endpoints
from clipatlas.settings.store import SettingsStore


class ReadOnlyCatalogStore(CatalogStore):
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path.resolve()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(f"file:{self._db_path.as_posix()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        return connection


class ReadOnlyProjectStore(ProjectStore):
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path.resolve()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(f"file:{self._db_path.as_posix()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        return connection


class ReadOnlyASRStore(ASRStore):
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path.resolve()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(f"file:{self._db_path.as_posix()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        return connection


class ReadOnlyOCRStore(OCRStore):
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path.resolve()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(f"file:{self._db_path.as_posix()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        return connection


def validate_data_root(value: Path) -> Path:
    root = value.expanduser().resolve()
    required = (root / "projects" / "projects.sqlite3", root / "library" / "library.sqlite3")
    if not root.is_dir() or any(not path.is_file() for path in required):
        raise ValueError("所选目录不是完整的 ClipAtlas 标注数据目录（应包含 projects 和 library）")
    return root


def _services(data_root: Path):
    settings_env: dict[str, str] = {}
    settings = SettingsStore(data_root / "config" / "settings.json", environment=settings_env)
    settings.apply_missing_environment()
    key = settings_env.get("CLIPATLAS_EMBEDDING_API_KEY", "").strip()
    base = settings_env.get("CLIPATLAS_EMBEDDING_BASE_URL", "").strip()
    model = settings_env.get("CLIPATLAS_EMBEDDING_MODEL", "text-embedding-v4").strip()
    dimensions = int(settings_env.get("CLIPATLAS_EMBEDDING_DIMENSIONS", "1024"))
    catalog = ReadOnlyCatalogStore(data_root / "library" / "library.sqlite3")
    semantic = None
    visual = None
    if key and base:
        semantic = SemanticSearchService(
            store=catalog,
            provider=QwenTextEmbeddingProvider(
                api_key=key, base_url=base, model=model, dimensions=dimensions,
            ),
        )
        try:
            native_base = derive_bailian_endpoints(base).dashscope_api_root
        except ValueError:
            native_base = "https://dashscope.aliyuncs.com/api/v1"
        visual = CoarseVideoSearchService(
            store=catalog,
            provider=QwenVLVideoEmbeddingProvider(api_key=key, base_http_api_url=native_base),
        )
    library_db = data_root / "library" / "library.sqlite3"
    hybrid = HybridSearchService(
        catalog=catalog, visual=visual,
        asr_store=ReadOnlyASRStore(library_db), ocr_store=ReadOnlyOCRStore(library_db),
    )
    return catalog, ReadOnlyProjectStore(data_root / "projects" / "projects.sqlite3"), semantic, visual, hybrid


def create_library_app(data_root: Path) -> FastAPI:
    root = validate_data_root(data_root)
    catalog, projects, semantic, visual, hybrid = _services(root)
    cache_root = (root / "library-cache").resolve()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.data_root = root

    @app.middleware("http")
    async def read_only(request: Request, call_next):
        if request.method not in {"GET", "HEAD"}:
            return JSONResponse({"detail": "独立素材库仅允许读取"}, status_code=403)
        return await call_next(request)

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "clipatlas", "version": "lan-standalone"}

    @app.get("/api/v1/projects")
    async def list_projects():
        return projects.list_projects()

    def scoped(project_id: UUID | None, video_ids: list[UUID] | None):
        if project_id is None:
            return video_ids
        allowed = catalog.list_video_ids_for_project(project_id)
        if video_ids is None:
            return allowed
        allowed_set = set(allowed)
        return list(dict.fromkeys(item for item in video_ids if item in allowed_set))

    @app.get("/api/v1/search/hybrid")
    async def search_hybrid(q: Annotated[str, Query(min_length=1)],
                            limit: Annotated[int, Query(ge=1, le=100)] = 10,
                            video_ids: Annotated[list[UUID] | None, Query()] = None,
                            project_id: UUID | None = None):
        return await hybrid.search(q.strip(), limit=limit, video_ids=scoped(project_id, video_ids))

    @app.get("/api/v1/search/segments")
    async def search_segments(q: Annotated[str, Query(min_length=1)],
                              limit: Annotated[int, Query(ge=1, le=100)] = 10,
                              video_ids: Annotated[list[UUID] | None, Query()] = None,
                              project_id: UUID | None = None):
        if semantic is None:
            raise HTTPException(503, "标注数据目录中未配置文本检索服务")
        return await semantic.search(q.strip(), limit=limit, video_ids=scoped(project_id, video_ids))

    @app.get("/api/v1/search/video-chunks")
    async def search_video(q: Annotated[str, Query(min_length=1)],
                           limit: Annotated[int, Query(ge=1, le=100)] = 10,
                           video_ids: Annotated[list[UUID] | None, Query()] = None,
                           project_id: UUID | None = None,
                           granularity: Annotated[Literal["5s", "30s"], Query()] = "5s"):
        if visual is None:
            raise HTTPException(503, "标注数据目录中未配置视觉检索服务")
        return await visual.search(q.strip(), limit=limit,
                                   video_ids=scoped(project_id, video_ids),
                                   profile=get_video_index_profile(granularity))

    @app.get("/api/v1/videos/{video_id}")
    async def video(video_id: UUID):
        item = catalog.get_video(video_id)
        if item is None:
            raise HTTPException(404, "video not found")
        stats = catalog.get_video_annotation_stats(video_id)
        return {"video": item, "segment_count": stats.segments_total, "annotation_stats": stats}

    @app.get("/api/v1/videos/{video_id}/index-thumbnail")
    async def thumbnail(video_id: UUID, timestamp_ms: Annotated[int, Query(ge=0)]):
        if catalog.get_video(video_id) is None:
            raise HTTPException(404, "video not found")
        uri = catalog.get_video_frame_uri(video_id, timestamp_ms)
        if uri:
            parsed = urlparse(uri)
            if parsed.scheme == "file" and parsed.netloc in ("", "localhost"):
                path = Path(url2pathname(parsed.path)).resolve()
                if path.is_relative_to(cache_root) and path.is_file():
                    return FileResponse(path, headers={"X-Content-Type-Options": "nosniff"})
        raise HTTPException(404, "cached frame not found")

    @app.get("/api/v1/videos/{video_id}/source-media")
    async def source_media(video_id: UUID):
        item = catalog.get_video(video_id)
        if item is None:
            raise HTTPException(404, "video not found")
        parsed = urlparse(item.source_uri)
        if parsed.scheme != "file" or parsed.netloc not in ("", "localhost"):
            raise HTTPException(404, "local source video not available")
        path = Path(url2pathname(parsed.path)).resolve()
        if path.suffix.lower() not in {".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi"} or not path.is_file():
            raise HTTPException(404, "source video missing or unsupported")
        media_type = "video/mp4" if path.suffix.lower() in {".mp4", ".m4v"} else (
            mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        )
        return FileResponse(path, media_type=media_type,
                            headers={"X-Content-Type-Options": "nosniff"})

    register_error_handlers(app)
    return app

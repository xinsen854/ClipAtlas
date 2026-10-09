import os
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


def mount_finecut_routes(app: FastAPI) -> Any:
    existing = getattr(app.state, "finecut_timeline_store", None)
    if existing is not None:
        return existing

    source_root = Path(__file__).resolve().parents[1] / "modules" / "finecut"
    try:
        from finecut.store import TimelineStore
    except ModuleNotFoundError as exc:
        if exc.name != "finecut" or not (source_root / "finecut" / "__init__.py").is_file():
            raise
        source_path = str(source_root)
        if source_path not in sys.path:
            sys.path.insert(0, source_path)
        from finecut.store import TimelineStore

    from clipatlas.api.routes.finecut import router as finecut_router

    store = TimelineStore(
        Path(os.getenv("CLIPATLAS_FINECUT_DB", "./data/finecut/finecut.sqlite3"))
    )
    app.state.finecut_timeline_store = store
    app.include_router(finecut_router)
    return store


def mount_frontend(app: FastAPI, dist_dir: Path) -> None:
    mount_finecut_routes(app)

    index_path = dist_dir / "index.html"
    if not index_path.is_file():
        return

    assets_dir = dist_dir / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

    for filename in ("logo.png", "favicon.png"):
        file_path = dist_dir / filename
        if file_path.is_file():
            app.add_api_route(
                f"/{filename}",
                lambda file_path=file_path: FileResponse(file_path),
                include_in_schema=False,
            )

    @app.get("/{full_path:path}", include_in_schema=False)
    async def frontend_fallback(full_path: str) -> FileResponse:
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404)
        return FileResponse(index_path)

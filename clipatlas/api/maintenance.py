"""Exclude destructive maintenance from active API writes, without serializing normal work."""

import re

from fastapi import FastAPI, Request
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import JSONResponse, Response


def install_maintenance_gate(app: FastAPI) -> None:
    app.state.active_mutations = 0
    app.state.maintenance_busy = False
    app.state.cache_restart_required = False

    @app.middleware("http")
    async def protect_maintenance(request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return await call_next(request)
        if app.state.cache_restart_required:
            return JSONResponse({"detail": "缓存目录已更改，请重启 ClipAtlas 后继续操作"}, status_code=409)
        exclusive = (
            request.method == "DELETE" and re.fullmatch(r"/api/v1/projects/[^/]+", request.url.path)
        ) or request.url.path == "/api/v1/library/cache-location"
        if app.state.maintenance_busy or (exclusive and app.state.active_mutations):
            return JSONResponse({"detail": "有操作正在进行，请完成后再删除项目或迁移缓存"}, status_code=409)
        if exclusive:
            app.state.maintenance_busy = True
        app.state.active_mutations += 1
        try:
            return await call_next(request)
        finally:
            app.state.active_mutations -= 1
            if exclusive:
                app.state.maintenance_busy = False

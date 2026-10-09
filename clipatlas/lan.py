"""LAN discovery and a deliberately narrow, streaming, read-only search gateway."""
from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask
from starlette.staticfiles import StaticFiles
from clipatlas.lan_files import LocalFiles, fingerprint, source_path

PORT = 29640
DISCOVERY_PORT = 29641
MAGIC = b"CLIPATLAS_SEARCH_DISCOVER_V1"
SERVICE = "clipatlas-lan-search"


class ConnectBody(BaseModel):
    address: str


class FolderBody(BaseModel):
    path: str


class MatchBody(BaseModel):
    connection: str
    video_id: str


ALLOWED = re.compile(
    r"^/(?:health|api/v1/projects|api/v1/search/(?:hybrid|segments|video-chunks)"
    r"|api/v1/videos/[0-9a-fA-F-]{36}/(?:index-thumbnail|source-media))$"
)


def normalize_address(value: str) -> str:
    value = value.strip().replace("\\", "/").strip("/")
    if "://" not in value:
        value = "http://" + value
    parts = urlsplit(value)
    if (parts.scheme != "http" or not parts.hostname or parts.username or parts.password
            or parts.path not in ("", "/") or parts.query or parts.fragment):
        raise ValueError("请输入电脑名或 IP，例如 \\\\DESKTOP-ABC 或 192.168.0.30")
    host = parts.hostname
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+", host):
        raise ValueError("电脑地址格式不正确")
    try:
        addresses = socket.getaddrinfo(host, parts.port or PORT, socket.AF_INET)
    except OSError as exc:
        raise ValueError("无法找到这台电脑，请尝试输入它的局域网 IP") from exc
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_private for a in addresses):
        raise ValueError("请使用局域网内的电脑地址")
    return f"http://{host}:{parts.port or PORT}"


def advertise(stop: threading.Event, port: int = PORT) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("0.0.0.0", DISCOVERY_PORT))
        sock.settimeout(0.5)
        while not stop.is_set():
            try:
                payload, address = sock.recvfrom(1024)
                if payload == MAGIC:
                    sock.sendto(json.dumps({"service": SERVICE, "name": socket.gethostname(),
                                            "port": port}).encode(), address)
            except socket.timeout:
                continue


def discover() -> list[dict]:
    found: dict[str, dict] = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(("0.0.0.0", 0))
        sock.settimeout(0.2)
        targets = {"255.255.255.255", "127.0.0.1"}
        try:
            for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                octets = item[4][0].split(".")
                if len(octets) == 4 and octets[0] not in {"127", "169"}:
                    targets.add(".".join((*octets[:3], "255")))
        except OSError:
            pass
        for _ in range(3):
            for target in targets:
                try:
                    sock.sendto(MAGIC, (target, DISCOVERY_PORT))
                except OSError:
                    pass
            time.sleep(0.08)
        deadline = time.monotonic() + 2.5
        while time.monotonic() < deadline:
            try:
                payload, address = sock.recvfrom(2048)
                info = json.loads(payload)
                if info.get("service") == SERVICE and 1 <= int(info["port"]) <= 65535:
                    url = f"http://{address[0]}:{int(info['port'])}"
                    found[url] = {"name": str(info["name"])[:100], "url": url}
            except (OSError, ValueError, KeyError, TypeError):
                continue
    return list(found.values())


async def proxy(request: Request, client: httpx.AsyncClient, upstream: str, path: str):
    if request.method not in ("GET", "HEAD") or not ALLOWED.fullmatch(path):
        raise HTTPException(403, "共享端只允许读取项目、搜索和预览素材")
    headers = {k: v for k, v in request.headers.items()
               if k.lower() in {"range", "if-range", "if-none-match", "if-modified-since"}}
    headers["accept-encoding"] = "identity"
    query = request.url.query
    url = upstream + path + ("?" + query if query else "")
    try:
        response = await client.send(client.build_request(request.method, url, headers=headers),
                                     stream=True)
    except httpx.HTTPError as exc:
        raise HTTPException(502, "无法连接素材库，请确认共享电脑上的素材库共享端已打开") from exc
    forwarded = {k: v for k, v in response.headers.items() if k.lower() in {
        "content-type", "content-length", "content-range", "accept-ranges", "etag",
        "last-modified", "content-disposition", "content-encoding"}}
    forwarded["cache-control"] = "no-store"
    return StreamingResponse(response.aiter_raw(), status_code=response.status_code,
                             headers=forwarded, background=BackgroundTask(response.aclose))


def create_gateway(*, host: bool = False, upstream: str = "http://127.0.0.1:8765",
                   frontend: Path | None = None, history_path: Path | None = None,
                   transport=None, reveal=None) -> FastAPI:
    connections: dict[str, str] = {}
    local_files = LocalFiles()
    folder_path = history_path.with_name("local-folder.json") if history_path else None
    history: list[dict] = []
    if history_path and history_path.is_file():
        try:
            saved = json.loads(history_path.read_text(encoding="utf-8"))
            for item in saved if isinstance(saved, list) else []:
                if isinstance(item, dict) and isinstance(item.get("url"), str):
                    item["url"] = re.sub(r":18765/?$", f":{PORT}", item["url"])
            history = [x for x in saved if isinstance(x, dict)
                       and isinstance(x.get("name"), str) and isinstance(x.get("url"), str)][:20]
        except (OSError, ValueError, TypeError):
            pass

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=5), trust_env=False,
                                     transport=transport) as client:
            app.state.http = client
            if folder_path and folder_path.is_file():
                try:
                    saved_root = json.loads(folder_path.read_text(encoding="utf-8"))["path"]
                    await asyncio.to_thread(local_files.scan, saved_root)
                except (OSError, ValueError, KeyError):
                    pass
            yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        # Reject browser cross-origin control calls, including localhost DNS rebinding.
        if not host:
            from starlette.responses import JSONResponse
            if request.url.hostname not in {"127.0.0.1", "localhost"}:
                return JSONResponse({"detail": "Invalid host"}, status_code=403)
            origin = request.headers.get("origin")
            if origin and origin != str(request.base_url).rstrip("/"):
                return JSONResponse({"detail": "Invalid origin"}, status_code=403)
        elif request.client:
            try:
                if not ipaddress.ip_address(request.client.host).is_private:
                    from starlette.responses import JSONResponse
                    return JSONResponse({"detail": "仅允许局域网访问"}, status_code=403)
            except ValueError:
                from starlette.responses import JSONResponse
                return JSONResponse({"detail": "无效的客户端地址"}, status_code=403)
        return await call_next(request)

    @app.get("/lan/info")
    async def info(request: Request):
        online = False
        if host:
            try:
                result = await request.app.state.http.get(upstream + "/health", timeout=3)
                online = result.status_code == 200 and result.json().get("service") == "clipatlas"
            except (httpx.HTTPError, ValueError):
                pass
        return {"service": SERVICE, "name": socket.gethostname(), "host": host,
                "online": online, "version": "1.0.4"}

    if host:
        @app.get("/lan/match/{video_id}")
        async def metadata(video_id: str, request: Request):
            from uuid import UUID
            try:
                UUID(video_id)
            except ValueError as exc:
                raise HTTPException(400, "素材编号无效") from exc
            try:
                result = await request.app.state.http.get(upstream + f"/api/v1/videos/{video_id}")
                result.raise_for_status()
                video = result.json()["video"]
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                raise HTTPException(502, "无法读取独立素材库中的素材信息") from exc
            info = {"filename": video["filename"], "size": None, "fingerprint": None}
            try:
                path = source_path(video["source_uri"])
                info["size"] = path.stat().st_size
                info["fingerprint"] = await asyncio.to_thread(fingerprint, path)
            except (OSError, ValueError):
                pass
            return info

        @app.api_route("/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"])
        async def host_proxy(request: Request, path: str):
            return await proxy(request, request.app.state.http, upstream, "/" + path)
        return app

    @app.get("/lan/hosts")
    async def hosts():
        return {"discovered": await asyncio.to_thread(discover), "history": history}

    @app.get("/lan/folder")
    async def folder_status():
        return local_files.status()

    @app.post("/lan/folder")
    async def folder_scan(body: FolderBody):
        try:
            result = await asyncio.to_thread(local_files.scan, body.path)
            if folder_path:
                folder_path.parent.mkdir(parents=True, exist_ok=True)
                folder_path.write_text(json.dumps({"path": body.path}), encoding="utf-8")
            return result
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/lan/local-match")
    async def local_match(body: MatchBody, request: Request):
        if body.connection not in connections:
            raise HTTPException(409, "请先连接共享电脑")
        if not re.fullmatch(r"[0-9a-fA-F-]{36}", body.video_id):
            raise HTTPException(400, "素材编号无效")
        if local_files.root is None:
            return {"status": "no-folder", "candidates": []}
        try:
            result = await request.app.state.http.get(
                connections[body.connection] + "/lan/match/" + body.video_id)
            result.raise_for_status()
            metadata = result.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(502, "无法核对原素材，请检查共享端连接") from exc
        return await asyncio.to_thread(local_files.match, metadata)

    @app.get("/lan/local/{key}/media")
    async def local_media(key: str):
        try:
            return FileResponse(local_files.get(key))
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/lan/local/{key}/reveal")
    async def local_reveal(key: str):
        try:
            path = local_files.get(key)
            if reveal:
                await asyncio.to_thread(reveal, path)
            else:
                import subprocess
                subprocess.Popen(["explorer.exe", f"/select,{path}"],
                                 creationflags=subprocess.CREATE_NO_WINDOW)
            return {"path": str(path)}
        except (ValueError, OSError) as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/lan/connect")
    async def connect(body: ConnectBody, request: Request):
        try:
            url = await asyncio.to_thread(normalize_address, body.address)
            response = await request.app.state.http.get(url + "/lan/info", timeout=6)
            response.raise_for_status()
            remote = response.json()
            if remote.get("service") != SERVICE or not remote.get("host"):
                raise ValueError("这台电脑没有运行 ClipAtlas 素材库共享端")
            if not remote.get("online"):
                raise ValueError("已找到共享电脑，请先在那台电脑上打开 ClipAtlas")
        except (ValueError, httpx.HTTPError) as exc:
            detail = str(exc) if isinstance(exc, ValueError) else "连接失败，请检查电脑地址、局域网和共享端防火墙"
            raise HTTPException(400, detail) from exc
        key = uuid4().hex
        connections[key] = url
        item = {"name": str(remote["name"]), "url": url}
        history[:] = [item] + [x for x in history if x["url"] != url][:19]
        if history_path:
            history_path.parent.mkdir(parents=True, exist_ok=True)
            history_path.write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
        return {**item, "prefix": f"/remote/{key}"}

    @app.api_route("/remote/{key}/{path:path}", methods=["GET", "HEAD", "POST", "PATCH", "DELETE"])
    async def client_proxy(request: Request, key: str, path: str):
        if key not in connections:
            raise HTTPException(409, "连接已失效，请重新选择共享电脑")
        return await proxy(request, request.app.state.http, connections[key], "/" + path)

    if frontend:
        app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")

        @app.get("/")
        async def index():
            return FileResponse(frontend / "lan.html")

    return app

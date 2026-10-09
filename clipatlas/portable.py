"""Portable launcher for the ClipAtlas desktop bundle.

Responsibilities (when frozen with PyInstaller):
1. Resolve the app root (folder next to ClipAtlas.exe) as the working dir so
   the default ``./data`` layout is written beside the executable.
2. Put the bundled ffmpeg/ffprobe on PATH.
3. Seed ``data/config/settings.json`` from the bundled template on first run.
4. Start uvicorn on a free localhost port and open a native desktop window
   (pywebview) pointed at the bundled frontend — no browser tab.
"""

from __future__ import annotations

import json  # noqa: F401  (kept for parity with future data migrations)
import os
import shutil
import socket
import sys
import threading
from pathlib import Path

from clipatlas import __version__

DEFAULT_PORT = 8765


def _log(message: str) -> None:
    print(message, flush=True)


def _app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _bundle_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent / "_internal"))
    return Path(__file__).resolve().parent.parent


def _free_port(preferred: int) -> int:
    for port in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return preferred


def _prepare_environment() -> tuple[Path, int]:
    root = _app_root()
    bundle = _bundle_root()

    bin_dir = bundle / "bin"
    if (bin_dir / "ffmpeg.exe").exists():
        os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")

    data_dir = root / "data"
    config_dir = data_dir / "config"
    settings_path = config_dir / "settings.json"

    template = bundle / "data-template"
    if template.is_dir():
        config_dir.mkdir(parents=True, exist_ok=True)
        if not settings_path.exists() and (template / "config" / "settings.json").exists():
            shutil.copy2(template / "config" / "settings.json", settings_path)
        for sub in ("library", "projects", "director", "narration", "roughcut", "exports"):
            (data_dir / sub).mkdir(parents=True, exist_ok=True)

    os.chdir(root)
    os.environ.setdefault("CLIPATLAS_HYPIT_AUTO_START", "1")

    if "CLIPATLAS_FRONTEND_DIST" not in os.environ:
        bundled_dist = bundle / "frontend_dist"
        if bundled_dist.is_dir():
            os.environ["CLIPATLAS_FRONTEND_DIST"] = str(bundled_dist)

    port = int(os.environ.get("CLIPATLAS_PORT", str(DEFAULT_PORT)))
    port = _free_port(port)
    return root, port


def _serve_http(app: object, port: int, ready: threading.Event) -> None:
    """Run uvicorn in a worker thread; signals readiness once it actually listens."""
    import asyncio

    import uvicorn

    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="warning", access_log=False
    )
    loop_factory = config.get_loop_factory()

    async def serve() -> None:
        server = uvicorn.Server(config)
        await server.serve()

    # Run uvicorn on its own event loop in a worker thread; the readiness
    # watcher below pings the port until it opens.
    def runner() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(serve())
        except BaseException as exc:  # noqa: BLE001
            _log(f"uvicorn 退出：{exc!r}")
        finally:
            loop.close()

    thread = threading.Thread(target=runner, daemon=True, name="clipatlas-uvicorn")
    thread.start()

    # Poll until the port accepts connections (startup) or the thread dies.
    import time

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if not thread.is_alive():
            _log("uvicorn 线程已退出，端口未就绪")
            break
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.25)
            try:
                probe.connect(("127.0.0.1", port))
                ready.set()
                _log(f"uvicorn 已监听 127.0.0.1:{port}")
                return
            except OSError:
                time.sleep(0.3)
    _log("等待 uvicorn 监听超时")


def _open_desktop_window(url: str) -> None:
    import webview

    window = webview.create_window(
        f"ClipAtlas v{__version__}",
        url,
        width=1360,
        height=880,
        min_size=(1024, 700),
        background_color="#F4F3EE",
    )
    try:
        webview.start(debug=os.environ.get("CLIPATLAS_WEBVIEW_DEBUG") == "1")
    except Exception as exc:  # noqa: BLE001
        _log(f"窗口启动失败：{exc!r}，回退到浏览器")
        import webbrowser

        webbrowser.open(url)
        import time

        while True:
            time.sleep(3600)


def _redirect_logs(log_dir: Path) -> None:
    """把 stdout/stderr 落到 data/logs/app.log，方便用户直接发日志排查。"""
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "app.log"
        fh = open(log_file, "a", encoding="utf-8", buffering=1)
        sys.stdout = fh
        sys.stderr = fh
    except Exception:
        pass


def main() -> int:
    root, port = _prepare_environment()
    _redirect_logs(root / "data" / "logs")
    _log(f"环境就绪：数据目录 {root / 'data'}，端口 {port}")

    def _probe(name: str) -> None:
        try:
            __import__(name)
            _log(f"probe ok: {name}")
        except BaseException as exc:  # noqa: BLE001
            _log(f"probe fail: {name}: {exc!r}")

    for _m in ("fastapi", "httpx", "pydantic", "opentimelineio", "scenedetect",
               "numpy", "PIL", "imageio", "pymediainfo", "comtypes", "uiautomation",
               "pyJianYingDraft", "dashscope"):
        _probe(_m)

    from clipatlas.main import app  # noqa: PLC0415  (after env is ready)

    _log("后端应用已加载")

    url = f"http://127.0.0.1:{port}"
    ready = threading.Event()
    threading.Thread(
        target=_serve_http, args=(app, port, ready), daemon=True, name="clipatlas-http"
    ).start()
    if not ready.wait(timeout=35):
        _log("后端未能按时就绪，仍然打开窗口")

    _open_desktop_window(url)
    return 0


def _hide_console() -> None:
    """PyInstaller console build: hide the backend log console immediately.

    Kept as console subsystem (windowed crashes for this pywebview app), then
    the black log window is hidden the moment the process starts.
    """
    try:
        import ctypes

        cw = ctypes.windll.kernel32.GetConsoleWindow()
        if cw:
            ctypes.windll.user32.ShowWindow(cw, 0)  # SW_HIDE
    except Exception:
        pass


if __name__ == "__main__":
    _hide_console()
    raise SystemExit(main())

# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the ClipAtlas portable desktop bundle (onedir)."""

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

# 源码根目录 = spec 所在目录（解压到哪里都能打包，不再写死机器路径）。
# PyInstaller 注入 SPECPATH（spec 所在目录），任何机器解压后都能打包。
PROJECT_ROOT = Path(SPECPATH)


def _find_ffmpeg_bin() -> Path:
    candidates: list[Path] = []
    env_bin = os.environ.get("CLIPATLAS_FFMPEG_BIN", "").strip()
    if env_bin:
        candidates.append(Path(env_bin))
    candidates.extend([
        PROJECT_ROOT / "ffmpeg" / "bin",
        PROJECT_ROOT / "vendor" / "ffmpeg" / "bin",
        Path(r"C:\ffmpeg\bin"),
    ])
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        win_get_root = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
        if win_get_root.is_dir():
            for pkg_dir in sorted(win_get_root.glob("Gyan.FFmpeg*")):
                for bin_dir in pkg_dir.rglob("bin"):
                    candidates.append(bin_dir)
    for cand in candidates:
        if not cand:
            continue
        if (cand / "ffmpeg.exe").exists() and (cand / "ffprobe.exe").exists():
            return cand
    raise SystemExit(
        "构建中止：未找到 ffmpeg.exe / ffprobe.exe。"
        "请设置环境变量 CLIPATLAS_FFMPEG_BIN 指向含二者的 bin 目录，"
        "或把 ffmpeg 放入项目 ffmpeg/bin 后重新打包；"
        "不允许生成缺失 FFmpeg 的残缺安装包。"
    )


FFMPEG_BIN = _find_ffmpeg_bin()

datas = []
binaries = []
hiddenimports = []

for exe_name in ("ffmpeg.exe", "ffprobe.exe"):
    binaries.append((str(FFMPEG_BIN / exe_name), "bin"))
datas = []
binaries = []
hiddenimports = []

for exe_name in ("ffmpeg.exe", "ffprobe.exe"):
    src = FFMPEG_BIN / exe_name
    if src.exists():
        binaries.append((str(src), "bin"))

# Frontend bundle
frontend_dist = PROJECT_ROOT / "frontend" / "dist"
if frontend_dist.is_dir():
    datas.append((str(frontend_dist), "frontend_dist"))

# First-run template: seed data/config/settings.json (masked secrets)
template_dir = PROJECT_ROOT / "build" / "data-template"
if (template_dir / "config" / "settings.json").is_file():
    datas.append((str(template_dir), "data-template"))

# Brand assets: installer header icon + future UI resources
assets_dir = PROJECT_ROOT / "assets"
if assets_dir.is_dir():
    datas.append((str(assets_dir), "assets"))

hypit_provider = PROJECT_ROOT / "clipatlas" / "hypit" / "wavespeed_provider"
if hypit_provider.is_dir():
    datas.append((str(hypit_provider), "clipatlas/hypit/wavespeed_provider"))

# Packages with dynamic imports that PyInstaller's default hooks miss.
_hidden_packages = [
    "uvicorn",
    "fastapi",
    "starlette",
    "httpx",
    "httpcore",
    "anyio",
    "pydantic",
    "multipart",
    "websockets",
    "httptools",
    "scenedetect",
    "opentimelineio",
    "pyJianYingDraft",
    "dashscope",
    "numpy",
    "imageio",
    "av",
    "webview",
    "bottle",
    "proxy_tools",
    "clr",
    "pythonnet",
]
for pkg in _hidden_packages:
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
        datas += pkg_datas
        binaries += pkg_binaries
        hiddenimports += pkg_hidden
    except Exception:
        hiddenimports += collect_submodules(pkg)

try:
    datas += copy_metadata("imageio")
except Exception:
    pass

# Dynamic-import modules inside the clipatlas package itself.
hiddenimports += [
    "clipatlas.embeddings.cloud_requests",
    "clipatlas.vendor.sentrysearch.qwen_cloud_embedder",
    "clipatlas.vendor.sentrysearch.base_embedder",
    "clipatlas.vendor.sentrysearch.chunker",
    "clipatlas.vendor.sentrysearch.dlq",
    "dotenv",
]

a = Analysis(
    [str(PROJECT_ROOT / "clipatlas" / "portable.py")],
    pathex=[str(PROJECT_ROOT), str(PROJECT_ROOT / "modules" / "finecut")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tests",
        "pytest",
        "mypy",
        "ruff",
        "tkinter.test",
        "matplotlib",
        "scipy",
    ],
    noarchive=False,
)

# Some audio-driver installations expose an obsolete private MSVCP140.dll on
# DLL search paths. PyInstaller may collect that copy and crash while loading
# OpenTimelineIO. Pin the supported system VC++ runtime instead.
a.binaries = type(a.binaries)(
    [entry for entry in a.binaries if entry[0].lower() != "msvcp140.dll"]
)
a.binaries.append(("MSVCP140.dll", r"C:\Windows\System32\MSVCP140.dll", "BINARY"))

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ClipAtlas",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # pywebview requires the console subsystem in this bundle; portable.py
    # hides the console immediately before creating the native window.
    console=True,
    disable_windowed_traceback=False,
    version=str(PROJECT_ROOT / "clipatlas_version_info.txt"),
    icon=str(PROJECT_ROOT / "assets" / "clipatlas_icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="ClipAtlas",
)

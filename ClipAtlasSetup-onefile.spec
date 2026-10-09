# -*- mode: python ; coding: utf-8 -*-
"""ClipAtlasSetup 单文件安装器（onefile console，内嵌便携包 app）。"""

import re
from pathlib import Path

# 源码根目录 = spec 所在目录（解压到哪里都能打包）。
# PyInstaller 注入 SPECPATH（spec 所在目录），任何机器解压后都能打包。
PROJECT_ROOT = Path(SPECPATH)
APP_SRC = PROJECT_ROOT / "dist" / "ClipAtlas"

# 从 clipatlas_version_info.txt 提取版本号，安装包带版本号命名（如 ClipAtlasSetup-v1.1.0.exe）。
_VER_SRC = PROJECT_ROOT / "clipatlas_version_info.txt"
_VERSION = "0.0.0"
try:
    _m = re.search(r"FileVersion', '([^']+)'", _VER_SRC.read_text(encoding="utf-8"))
    if _m:
        _VERSION = _m.group(1)
except Exception:
    pass

datas = []
binaries = []
hiddenimports = []

# 内嵌便携包全量（安装时从 _MEIPASS/app 复制到安装目录）
if APP_SRC.is_dir():
    datas.append((str(APP_SRC), "app"))

a = Analysis(
    [str(PROJECT_ROOT / "installer.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter.test"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=f"ClipAtlasSetup-v{_VERSION}",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    version=str(PROJECT_ROOT / "clipatlas_version_info.txt"),
    icon=str(PROJECT_ROOT / "assets" / "clipatlas_icon.ico"),
)

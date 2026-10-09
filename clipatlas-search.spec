# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH)
datas = [(str(root / 'frontend' / 'dist-lan'), 'frontend/dist-lan')]
binaries = []
hiddenimports = []
for package in ('webview', 'uvicorn', 'dashscope'):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h
hiddenimports += [
    'clipatlas.embeddings.cloud_requests',
    'clipatlas.vendor.sentrysearch.qwen_cloud_embedder',
]

a = Analysis([str(root / 'clipatlas' / 'lan_entry.py')], pathex=[str(root)],
    binaries=binaries, datas=datas, hiddenimports=hiddenimports,
    excludes=['pytest', 'numpy', 'scipy', 'matplotlib', 'pandas', 'IPython', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6'])
# DashScope's optional modules may expose an obsolete private MSVCP140.dll.
# Use the supported Windows VC++ runtime, matching the main ClipAtlas bundle.
a.binaries = type(a.binaries)(
    [entry for entry in a.binaries if entry[0].lower() != 'msvcp140.dll']
)
a.binaries.append(('MSVCP140.dll', r'C:\Windows\System32\MSVCP140.dll', 'BINARY'))
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='ClipAtlasSearchSetup',
    console=False, upx=False, icon=str(root / 'assets' / 'clipatlas_icon.ico'))

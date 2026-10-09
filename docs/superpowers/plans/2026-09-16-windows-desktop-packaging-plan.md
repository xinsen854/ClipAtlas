# ClipAtlas Windows Desktop Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the existing pywebview + PyInstaller desktop path so ClipAtlas installs and launches as a Windows 10/11 desktop application without requiring a browser or persistent console window.

**Architecture:** Reuse `clipatlas/portable.py` as the single desktop launcher, `clipatlas-portable.spec` as the portable bundle definition, and `installer.py` + `ClipAtlasSetup-onefile.spec` as the installer path. Do not introduce Electron/Tauri or any second frontend/backend/state model.

**Tech Stack:** Python 3.12, FastAPI, pywebview, PyInstaller, React/Vite, FFmpeg/ffprobe, pyJianYingDraft, Windows WebView2.

**Spec:** `docs/superpowers/specs/2026-09-16-windows-desktop-packaging-design.md`

## Global Constraints

- Windows target: Windows 10/11 x64.
- Preserve one existing FastAPI backend and one existing React frontend.
- Do not modify TimelineDocument/FineCut contracts or editing semantics.
- Do not add Electron, Tauri, cloud export, updater, publish system, DRM, or a second store.
- Desktop mode must use bundled frontend assets and localhost only.
- Normal installed launch must not require a browser and must not leave a persistent console window visible.
- FFmpeg/ffprobe are hard build/runtime dependencies for the packaged app.
- User data must survive restart and normal upgrade/reinstall flows.

---

### Task 1: Freeze Phase 7B Base And Create Desktop Branch

**Files:**
- Existing branch: `feat/intelligent-finecut-external-workspace-v0.1`
- New branch: `feat/windows-desktop-packaging-v1`

**Interfaces:**
- Consumes: Phase 7B validated repository state.
- Produces: isolated desktop-packaging branch.

- [ ] **Step 1: Verify the Phase 7B repository state**

Run:

```powershell
cd D:\ClipAtlas\clipatlas
git status --short
git rev-parse HEAD
```

Expected: only intentional Phase 7B changes, or clean after syncing the accepted Phase 7B commit.

- [ ] **Step 2: Run the accepted Phase 7B regression once on the base**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: `1050 passed, 2 skipped` (or a higher count only if new accepted tests have been added), with no failures.

- [ ] **Step 3: Sync the base branch**

```powershell
git fetch origin feat/intelligent-finecut-external-workspace-v0.1
git merge --ff-only origin/feat/intelligent-finecut-external-workspace-v0.1
```

- [ ] **Step 4: Create/switch to the desktop branch**

```powershell
git switch -c feat/windows-desktop-packaging-v1
```

If the branch already exists remotely:

```powershell
git switch feat/windows-desktop-packaging-v1
git merge --ff-only origin/feat/windows-desktop-packaging-v1
```

---

### Task 2: Audit Existing Portable Launcher And Packaging Inputs

**Files:**
- Inspect: `clipatlas/portable.py`
- Inspect: `clipatlas-portable.spec`
- Inspect: `installer.py`
- Inspect: `ClipAtlasSetup-onefile.spec`
- Inspect: `frontend/package.json`
- Test/Create only if needed: `tests/test_portable_launcher.py`

**Interfaces:**
- Consumes: existing desktop launcher and PyInstaller definitions.
- Produces: exact list of packaging blockers without changing architecture.

- [ ] **Step 1: Verify required runtime imports are declared or collected**

Check that packaging covers at least:

```text
fastapi
uvicorn
pydantic
opentimelineio
scenedetect
numpy
PIL/imageio
pymediainfo
comtypes/uiautomation
pyJianYingDraft
dashscope
webview
finecut runtime modules
```

- [ ] **Step 2: Verify the frontend bundle contract**

Confirm `frontend/dist` is added to the bundle as `frontend_dist` and `portable.py` sets `CLIPATLAS_FRONTEND_DIST` to that directory when frozen.

- [ ] **Step 3: Verify mutable-data location**

Confirm `portable.py` never writes application data under `sys._MEIPASS`; mutable data must resolve from the executable/app root or another persistent user path.

- [ ] **Step 4: Verify installer shortcut and prerequisite behavior**

Confirm `installer.py` checks WebView2 and VC++ and creates desktop/start-menu shortcuts targeting installed `ClipAtlas.exe`.

- [ ] **Step 5: Do not modify production unless a concrete blocker is demonstrated**

Record each blocker as a failing focused test or reproducible build error before changing code.

---

### Task 3: Add Focused Launcher Tests

**Files:**
- Create or modify: `tests/test_portable_launcher.py`
- Modify only if tests prove necessary: `clipatlas/portable.py`

**Interfaces:**
- Consumes: `_free_port`, `_prepare_environment`, `_app_root`, `_bundle_root` behaviors.
- Produces: regression coverage for persistent data path, bundled frontend path, and port fallback.

- [ ] **Step 1: Write a failing test for persistent app data outside bundle extraction**

Test frozen-path behavior by monkeypatching `sys.frozen`, `sys.executable`, and `sys._MEIPASS`; assert app root follows the executable directory while bundle root follows `_MEIPASS`.

- [ ] **Step 2: Run the focused test**

```powershell
.\.venv\Scripts\python.exe -m pytest .\tests\test_portable_launcher.py -q
```

Expected: FAIL only if current implementation violates the persistent/bundle separation contract.

- [ ] **Step 3: Write a focused test for `CLIPATLAS_FRONTEND_DIST`**

Create a fake bundle containing `frontend_dist`, run environment preparation with isolated temp paths, and assert the environment variable points to the bundled frontend directory.

- [ ] **Step 4: Write a focused test for preferred-port fallback**

Occupy port 8765 temporarily and assert `_free_port(8765)` returns a different available port in the allowed range.

- [ ] **Step 5: Apply only minimal launcher fixes required by failing tests**

Do not add process managers, services, or new desktop state.

- [ ] **Step 6: Re-run focused tests**

```powershell
.\.venv\Scripts\python.exe -m pytest .\tests\test_portable_launcher.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add tests/test_portable_launcher.py clipatlas/portable.py
git commit -m "test: harden desktop launcher runtime"
```

Only include `clipatlas/portable.py` if it actually changed.

---

### Task 4: Build Production Frontend

**Files:**
- Read: `frontend/package.json`
- Generated: `frontend/dist/**`

**Interfaces:**
- Consumes: existing React/Vite frontend.
- Produces: production static assets consumed by PyInstaller.

- [ ] **Step 1: Run frontend tests**

```powershell
cd D:\ClipAtlas\clipatlas\frontend
npm run test:run -- --maxWorkers=1 --fileParallelism=false
```

Expected: PASS.

- [ ] **Step 2: Run typecheck**

```powershell
npm run typecheck
```

Expected: PASS.

- [ ] **Step 3: Build production assets**

```powershell
npm run build
```

Expected: `frontend/dist` created successfully.

- [ ] **Step 4: Verify the build directory exists**

```powershell
Test-Path D:\ClipAtlas\clipatlas\frontend\dist
```

Expected: `True`.

---

### Task 5: Build And Smoke-Test Portable Desktop Bundle

**Files:**
- Build definition: `clipatlas-portable.spec`
- Generated: `dist/ClipAtlas/**`

**Interfaces:**
- Consumes: production frontend, Python runtime graph, FFmpeg, assets.
- Produces: `dist/ClipAtlas/ClipAtlas.exe` portable desktop app.

- [ ] **Step 1: Verify FFmpeg input**

```powershell
$env:CLIPATLAS_FFMPEG_BIN
Test-Path "$env:CLIPATLAS_FFMPEG_BIN\ffmpeg.exe"
Test-Path "$env:CLIPATLAS_FFMPEG_BIN\ffprobe.exe"
```

If the environment variable is empty, use one of the locations already supported by the spec. Do not weaken the hard failure in the spec.

- [ ] **Step 2: Ensure PyInstaller is available in the venv**

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --version
```

- [ ] **Step 3: Build the portable bundle**

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --clean .\clipatlas-portable.spec
```

Expected: `dist\ClipAtlas\ClipAtlas.exe` exists.

- [ ] **Step 4: Launch the portable executable**

```powershell
Start-Process .\dist\ClipAtlas\ClipAtlas.exe
```

Verify manually:

```text
- Native ClipAtlas window opens.
- No manual browser navigation is required.
- No persistent console window remains visible.
- Existing ClipAtlas UI loads.
- data/logs/app.log is created.
```

- [ ] **Step 5: Inspect startup log after launch**

```powershell
Get-Content .\dist\ClipAtlas\data\logs\app.log -Tail 120
```

Expected: backend loaded, loopback port listened, and required dependency probes are understandable. Any failed hard-runtime probe must be investigated before installer build.

- [ ] **Step 6: Test one FFmpeg-dependent operation and Jianying dependency presence**

Use the existing UI to perform a minimal media operation and confirm no `ffmpeg`/`ffprobe` resolution error. Confirm `pyJianYingDraft` probe is successful when Jianying export is included.

---

### Task 6: Build And Smoke-Test Installer

**Files:**
- Build definition: `ClipAtlasSetup-onefile.spec`
- Installer implementation: `installer.py`
- Generated installer: `dist/ClipAtlasSetup-vX.X.X.exe`

**Interfaces:**
- Consumes: `dist/ClipAtlas/**` portable bundle.
- Produces: single-file Windows installer.

- [ ] **Step 1: Build installer only after portable smoke test passes**

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --clean .\ClipAtlasSetup-onefile.spec
```

Expected: versioned installer executable under `dist`.

- [ ] **Step 2: Install into an isolated test directory**

Run the generated installer and select a clean path such as:

```text
D:\ClipAtlasDesktopTest\ClipAtlas
```

Verify WebView2/VC++ prerequisite checks show correct status.

- [ ] **Step 3: Verify shortcuts**

Confirm both desktop and Start-menu shortcuts target the installed `ClipAtlas.exe` rather than Python, PowerShell, Vite, or a browser URL.

- [ ] **Step 4: Launch from the desktop shortcut**

Verify the same portable smoke-test criteria:

```text
- native window
- no required browser tab
- no persistent console
- existing UI loads
- data/logs/app.log available
```

- [ ] **Step 5: Verify persistence**

Create a harmless local setting/project entry, close ClipAtlas, reopen it from the shortcut, and confirm the data remains.

- [ ] **Step 6: Verify reinstall/upgrade does not silently destroy mutable data**

Re-run the installer over the same test install only if the current installer semantics support it. Confirm user data survives; if the installer intentionally forbids or replaces existing installs, document the actual behavior instead of inventing migration logic.

---

### Task 7: Final Regression And Diff Audit

**Files:**
- Any files changed by Tasks 3-6 only.

**Interfaces:**
- Consumes: completed desktop hardening.
- Produces: release candidate evidence.

- [ ] **Step 1: Run Python regression**

```powershell
cd D:\ClipAtlas\clipatlas
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: no failures.

- [ ] **Step 2: Run frontend regression**

```powershell
cd D:\ClipAtlas\clipatlas\frontend
npm run test:run -- --maxWorkers=1 --fileParallelism=false
npm run typecheck
```

Expected: both pass.

- [ ] **Step 3: Audit diff**

```powershell
cd D:\ClipAtlas\clipatlas
git diff --stat cc35c8f3a059cc57c4ac3da2b7fdc7267de8d079..HEAD
git status --short
```

The actual desktop base SHA must replace the old Phase 7A SHA if Phase 7B has advanced the base before implementation.

- [ ] **Step 4: Confirm scope**

Explicitly verify no changes to:

```text
TimelineDocument / FineCut contracts
editing semantics
second backend/frontend/store
cloud export
A1 mixdown
publish system
DRM/licensing
```

- [ ] **Step 5: Commit final desktop hardening changes**

```powershell
git add <only intended desktop files>
git commit -m "feat: harden Windows desktop packaging"
```

- [ ] **Step 6: Record final evidence**

Report:

```text
Portable EXE path
Installer EXE path
Python test count
Frontend test count
Typecheck result
Desktop shortcut launch result
Native-window result
Console visibility result
Data persistence result
FFmpeg result
Jianying dependency result
Diff stat
Final HEAD
Git status
```

Stop after this phase. Do not begin updater/cloud/publishing work.

# ClipAtlas Windows Desktop Packaging Design

## Goal

Deliver ClipAtlas as a Windows 10/11 desktop application that launches from a desktop/start-menu shortcut, opens in a native application window, does not require the user to open a browser, and does not show a persistent console window.

## Existing Architecture To Reuse

ClipAtlas already has the required desktop foundation:

- `clipatlas/portable.py` starts the local FastAPI application on loopback, prepares the local data directory, exposes bundled FFmpeg, points the app at bundled frontend assets, launches a native `pywebview` window, and hides the console when frozen.
- `clipatlas-portable.spec` packages the Python backend, `frontend/dist`, FFmpeg/ffprobe, application assets, dynamic dependencies, `pyJianYingDraft`, and `pywebview` into an onedir `ClipAtlas` bundle.
- `installer.py` is a Windows installer UI that checks WebView2 and VC++ runtime prerequisites, copies the portable bundle, and creates desktop/start-menu shortcuts.
- `ClipAtlasSetup-onefile.spec` packages that installer as a single executable containing the portable application bundle.

The desktop phase will harden this existing path. It will not introduce Electron, Tauri, a second backend, or a second frontend.

## Product Behavior

The target user flow is:

1. User runs `ClipAtlasSetup-vX.X.X.exe`.
2. Installer checks required Windows runtime dependencies.
3. Installer installs the existing ClipAtlas portable bundle and creates shortcuts.
4. User launches `ClipAtlas` from desktop or Start menu.
5. `ClipAtlas.exe` starts the existing FastAPI backend on `127.0.0.1` using an available local port.
6. The bundled frontend is served by the existing backend.
7. `pywebview` opens the frontend in a native Windows application window.
8. No browser tab is required and no persistent console window is visible.
9. User data, settings, indexes, projects, exports, and logs survive application restarts and upgrades.

## Data And State

Desktop packaging must not create a second application state model.

- Existing backend stores remain authoritative.
- Existing frontend remains the only UI application.
- Existing `TimelineDocument`, FineCut state, export state, library state, and settings contracts remain unchanged.
- Packaged application resources are read-only inputs.
- Mutable user data remains outside PyInstaller's temporary extraction directory and survives restarts.

The current `portable.py` app-root/data behavior should be preserved unless testing proves it unsafe for installed builds. Any data-directory adjustment must be narrowly scoped and migration-safe.

## Desktop Runtime

### Backend lifecycle

`portable.py` remains the single desktop launcher. It is responsible for:

- preparing runtime environment;
- resolving bundled assets;
- adding bundled FFmpeg/ffprobe to `PATH`;
- selecting a free loopback port;
- starting the existing FastAPI `clipatlas.main:app`;
- waiting for backend readiness;
- opening the native window;
- logging startup failures.

No extra process manager or desktop service is introduced.

### Frontend

The production frontend is built with the existing `frontend/package.json` build command and bundled from `frontend/dist`.

Development continues to use Vite normally. Desktop packaging must not change the development frontend architecture.

### Native window

Continue using `pywebview`.

Required behavior:

- title includes ClipAtlas version;
- minimum size remains usable for the existing UI;
- closing the native window terminates the desktop application cleanly;
- fallback to a browser is allowed only when native-window startup fails and must be logged;
- no persistent console window in normal packaged use.

## Packaging

### Portable bundle

`clipatlas-portable.spec` remains the portable application build definition.

The build must include:

- ClipAtlas Python packages;
- FineCut modules needed at runtime;
- built frontend assets;
- FFmpeg and ffprobe;
- application icons/assets;
- required dynamic Python modules;
- `pyJianYingDraft` and its runtime dependencies when Jianying export is supported;
- `pywebview` runtime dependencies.

A build must fail rather than silently produce an incomplete bundle when a hard dependency such as FFmpeg is missing.

### Installer

`installer.py` + `ClipAtlasSetup-onefile.spec` remain the Windows installer path.

The installer must:

- support Windows 10/11 x64;
- validate WebView2 Runtime;
- validate VC++ Redistributable;
- allow the installation directory to be chosen;
- create desktop and Start-menu shortcuts;
- preserve mutable application data across reinstall/upgrade when appropriate;
- launch the installed executable without requiring a terminal.

## Error Handling And Diagnostics

Desktop packaging must make failures diagnosable without exposing a console to normal users.

- Startup logs go to the existing `data/logs/app.log` path.
- Dependency probes remain logged.
- Backend startup timeout is logged explicitly.
- Native-window startup failure is logged before browser fallback.
- Packaging tests must distinguish missing build dependencies from application runtime regressions.

Do not add telemetry or cloud logging in this phase.

## Security And Scope Boundaries

This phase does not add:

- Electron or Tauri;
- a cloud backend;
- updater service;
- auto-update mechanism;
- publish system;
- DRM or licensing;
- new authentication;
- a second API server;
- a second application state/store;
- changes to `TimelineDocument` or FineCut editing semantics.

The desktop wrapper only packages and launches the existing application.

## Verification Strategy

Verification proceeds in layers:

1. Existing Python test suite remains green.
2. Existing frontend Vitest suite remains green.
3. Frontend typecheck remains green.
4. Add focused tests for portable launcher helpers where they can be tested without a GUI.
5. Build `frontend/dist`.
6. Build the portable PyInstaller bundle.
7. Launch `dist/ClipAtlas/ClipAtlas.exe` on Windows and verify:
   - native window opens;
   - backend becomes ready;
   - no browser tab is required;
   - no persistent console window remains;
   - bundled frontend loads;
   - existing data is readable/writable;
   - FFmpeg-dependent operations resolve bundled executables;
   - Jianying dependency probe succeeds when packaged.
8. Build `ClipAtlasSetup-vX.X.X.exe`.
9. Install into a clean test directory and verify shortcuts, launch, data persistence, and uninstall/reinstall behavior relevant to this installer.

## Stop Conditions

Stop and reassess before continuing if any implementation requires:

- changing `TimelineDocument` or FineCut contracts;
- introducing a second backend or UI stack;
- replacing the existing pywebview/PyInstaller architecture;
- moving mutable user data in a way that can lose existing user data;
- weakening existing export/library behavior merely to make packaging pass;
- bypassing Windows security or runtime requirements.

## Acceptance Criteria

Desktop packaging is accepted when:

- a Windows installer executable can be built reproducibly from the repository;
- installed ClipAtlas launches by double-click from a shortcut;
- the user sees the existing ClipAtlas UI in a native window rather than manually opening a browser;
- normal use does not leave a console window visible;
- backend/frontend functionality remains the same application, not duplicated desktop implementations;
- existing automated backend/frontend regression suites pass;
- portable and installer smoke tests pass on Windows 10/11 x64;
- no application-domain schema or FineCut editing semantics were changed.

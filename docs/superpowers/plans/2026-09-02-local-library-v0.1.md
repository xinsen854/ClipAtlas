# Local Library V0.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a persistent local-folder video library that discovers media in place, queues new/changed files, processes one video at a time, and resumes safely after restart.

**Architecture:** Add a `clipatlas.library` subsystem around SQLite persistence, a local folder scanner, an existing-file preparation service that reuses current ffprobe/PySceneDetect/frame extraction adapters, a sequential worker, and a periodic supervisor. Original media stays in the user's folder; generated artifacts go only to ClipAtlas-owned cache paths.

**Tech Stack:** Python 3.12, stdlib `sqlite3`, `asyncio`, FastAPI, Pydantic v2, existing FFmpeg/ffprobe + PySceneDetect adapters, Pytest, Ruff, Mypy.

**Spec:** `docs/superpowers/specs/2026-09-02-local-library-v0.1.md`

## Global Constraints

- Original local media is never copied or modified by the Local Library path.
- Generated frames/cache must stay under `CLIPATLAS_LIBRARY_CACHE`, default `./data/library-cache`.
- Queue state persists in SQLite at `CLIPATLAS_LIBRARY_DB`, default `./data/clipatlas-library.sqlite3`.
- Fast fingerprint is SHA256 of canonical path + size + `mtime_ns`; it is not a content hash.
- Supported extensions are `.mp4`, `.mov`, `.mkv`, `.avi`, `.webm`, `.m4v`, case-insensitive.
- Processing concurrency is exactly 1 in V0.1.
- In-flight statuses recover to `QUEUED` after restart.
- Unchanged `COMPLETED` files are never reprocessed automatically.
- Unchanged `FAILED` files are not retried automatically; retry is explicit.
- Existing upload/provider APIs must remain backward compatible.
- No AI provider calls are added in this subsystem.

---

### Task 1: Library domain models and fast fingerprint

**Files:**
- Create: `clipatlas/library/__init__.py`
- Create: `clipatlas/library/models.py`
- Create: `clipatlas/library/fingerprint.py`
- Test: `tests/library/test_models.py`
- Test: `tests/library/test_fingerprint.py`

**Interfaces:**
- Produces: `LibraryItemStatus(str, Enum)` with `QUEUED`, `PROBING`, `SCENE_DETECTION`, `FRAME_EXTRACTION`, `COMPLETED`, `FAILED`, `MISSING`.
- Produces: `LibraryRoot`, `LibraryItem`, `ScanReport` Pydantic models.
- Produces: `canonicalize_path(path: Path) -> Path`.
- Produces: `fast_fingerprint(path: Path, size_bytes: int, mtime_ns: int) -> str`.

- [ ] **Step 1: Write failing model and fingerprint tests**

```python
from pathlib import Path

from clipatlas.library.fingerprint import fast_fingerprint
from clipatlas.library.models import LibraryItemStatus


def test_library_status_contains_persistent_queue_stages() -> None:
    assert {status.value for status in LibraryItemStatus} == {
        "QUEUED",
        "PROBING",
        "SCENE_DETECTION",
        "FRAME_EXTRACTION",
        "COMPLETED",
        "FAILED",
        "MISSING",
    }


def test_fast_fingerprint_is_deterministic_and_changes_with_metadata(tmp_path: Path) -> None:
    path = (tmp_path / "Movie.MP4").resolve()
    first = fast_fingerprint(path, 100, 123)
    assert first == fast_fingerprint(path, 100, 123)
    assert first != fast_fingerprint(path, 101, 123)
    assert first != fast_fingerprint(path, 100, 124)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest tests/library/test_models.py tests/library/test_fingerprint.py -v`
Expected: import failure because `clipatlas.library` does not exist.

- [ ] **Step 3: Implement minimal models and fingerprinting**

`models.py` must define:

```python
class LibraryItemStatus(str, Enum):
    QUEUED = "QUEUED"
    PROBING = "PROBING"
    SCENE_DETECTION = "SCENE_DETECTION"
    FRAME_EXTRACTION = "FRAME_EXTRACTION"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    MISSING = "MISSING"


class LibraryRoot(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    path: str
    recursive: bool = True
    enabled: bool = True
    created_at: datetime = Field(default_factory=utc_now)


class LibraryItem(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    root_id: UUID
    source_path: str
    size_bytes: int = Field(ge=0)
    mtime_ns: int = Field(ge=0)
    fingerprint: str
    processed_fingerprint: str | None = None
    status: LibraryItemStatus = LibraryItemStatus.QUEUED
    video_id: UUID | None = None
    attempts: int = Field(default=0, ge=0)
    last_error: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ScanReport(BaseModel):
    discovered: int = 0
    changed: int = 0
    missing: int = 0
    unchanged: int = 0
```

`fast_fingerprint()` must hash `f"{path}\0{size_bytes}\0{mtime_ns}".encode("utf-8")` with SHA256.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `pytest tests/library/test_models.py tests/library/test_fingerprint.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `feat: add local library domain models`

---

### Task 2: SQLite LibraryStore and durable queue semantics

**Files:**
- Create: `clipatlas/library/store.py`
- Test: `tests/library/test_store.py`

**Interfaces:**
- Consumes: `LibraryRoot`, `LibraryItem`, `LibraryItemStatus`.
- Produces: `LibraryStore(db_path: Path)`.
- Produces methods:
  - `add_root(path: Path, recursive: bool = True) -> LibraryRoot`
  - `list_roots(enabled_only: bool = False) -> list[LibraryRoot]`
  - `get_item_by_path(source_path: Path) -> LibraryItem | None`
  - `list_items(root_id: UUID | None = None, status: LibraryItemStatus | None = None, limit: int = 100, offset: int = 0) -> list[LibraryItem]`
  - `save_observation(root_id: UUID, source_path: Path, size_bytes: int, mtime_ns: int, fingerprint: str) -> str`
  - `mark_missing(item_id: UUID) -> None`
  - `claim_next() -> LibraryItem | None`
  - `set_status(item_id: UUID, status: LibraryItemStatus) -> None`
  - `complete(item_id: UUID, video_id: UUID) -> None`
  - `fail(item_id: UUID, error: str) -> None`
  - `retry(item_id: UUID) -> bool`
  - `recover_interrupted() -> int`
  - `counts_by_status() -> dict[LibraryItemStatus, int]`

`save_observation()` returns one of literal strings: `"discovered"`, `"changed"`, `"unchanged"`, `"restored"`.

- [ ] **Step 1: Write failing persistence and queue tests**

Tests must prove all of the following with a temporary DB:

```python
store = LibraryStore(tmp_path / "library.sqlite3")
root = store.add_root(tmp_path / "media")
assert store.list_roots()[0].id == root.id

outcome = store.save_observation(root.id, movie, 100, 123, "fp1")
assert outcome == "discovered"
item = store.get_item_by_path(movie)
assert item is not None and item.status is LibraryItemStatus.QUEUED

claimed = store.claim_next()
assert claimed is not None
assert claimed.attempts == 1
assert claimed.status is LibraryItemStatus.PROBING

store.complete(claimed.id, video_id)
completed = store.get_item_by_path(movie)
assert completed is not None
assert completed.status is LibraryItemStatus.COMPLETED
assert completed.processed_fingerprint == completed.fingerprint

reopened = LibraryStore(tmp_path / "library.sqlite3")
assert reopened.get_item_by_path(movie).video_id == video_id
```

Also test:
- changed fingerprint clears `video_id`, `processed_fingerprint`, `last_error`, sets `QUEUED`;
- unchanged completed remains `COMPLETED`;
- unchanged failed remains `FAILED`;
- `claim_next()` selects oldest queued item and increments attempts atomically;
- `recover_interrupted()` converts `PROBING`, `SCENE_DETECTION`, `FRAME_EXTRACTION` to `QUEUED` but leaves other states unchanged;
- `retry()` only requeues `FAILED` items;
- stored error is truncated to at most 2000 characters.

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest tests/library/test_store.py -v`
Expected: import failure for `clipatlas.library.store`.

- [ ] **Step 3: Implement SQLite schema and methods**

Use stdlib `sqlite3`. On construction create parent directory and initialize:

```sql
CREATE TABLE IF NOT EXISTS library_roots (
    id TEXT PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    recursive INTEGER NOT NULL,
    enabled INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS library_items (
    id TEXT PRIMARY KEY,
    root_id TEXT NOT NULL,
    source_path TEXT NOT NULL UNIQUE,
    size_bytes INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    fingerprint TEXT NOT NULL,
    processed_fingerprint TEXT,
    status TEXT NOT NULL,
    video_id TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(root_id) REFERENCES library_roots(id)
);

CREATE INDEX IF NOT EXISTS idx_library_items_status_created
ON library_items(status, created_at);
```

`claim_next()` must use one connection/transaction with `BEGIN IMMEDIATE`, select oldest `QUEUED`, then update the same row to `PROBING` and increment `attempts` before committing.

- [ ] **Step 4: Run store tests and full regression**

Run: `pytest tests/library/test_store.py -v`
Expected: PASS.

Run: `pytest -q`
Expected: all existing tests still PASS.

- [ ] **Step 5: Commit**

Commit message: `feat: add persistent local library store`

---

### Task 3: Local folder scanner and scan reconciliation

**Files:**
- Create: `clipatlas/library/scanner.py`
- Test: `tests/library/test_scanner.py`

**Interfaces:**
- Consumes: `LibraryStore`, `LibraryRoot`, `ScanReport`, `fast_fingerprint`.
- Produces: `SUPPORTED_VIDEO_EXTENSIONS: frozenset[str]`.
- Produces: `LocalFolderScanner(store: LibraryStore)`.
- Produces: `scan_root(root: LibraryRoot) -> ScanReport`.
- Produces: `scan_all() -> ScanReport`.

- [ ] **Step 1: Write failing scanner tests**

Create nested temp files:

```text
media/
  one.mp4
  TWO.MOV
  ignore.txt
  nested/
    three.mkv
```

Assert recursive scan discovers 3 videos, ignores text, and a non-recursive root discovers only 2 top-level videos.

Then test reconciliation:

1. first scan -> `discovered == 3`;
2. second unchanged scan -> `unchanged == 3`;
3. modify `one.mp4` bytes and timestamp -> `changed == 1` and item becomes `QUEUED`;
4. delete `TWO.MOV` -> `missing == 1` and item becomes `MISSING`;
5. re-create a previously completed file with the exact stored processed fingerprint -> status restores `COMPLETED`;
6. symlinked video escaping the configured root is skipped when symlinks are supported by the test platform.

- [ ] **Step 2: Run scanner tests and verify RED**

Run: `pytest tests/library/test_scanner.py -v`
Expected: import failure for scanner module.

- [ ] **Step 3: Implement scanner**

Use `Path.iterdir()` for non-recursive and `Path.rglob("*")` for recursive roots. For every candidate:

```python
if candidate.is_symlink() or not candidate.is_file():
    continue
if candidate.suffix.lower() not in SUPPORTED_VIDEO_EXTENSIONS:
    continue
resolved = candidate.resolve()
if not resolved.is_relative_to(root_path):
    continue
stat = resolved.stat()
fingerprint = fast_fingerprint(resolved, stat.st_size, stat.st_mtime_ns)
outcome = store.save_observation(...)
```

After walking the root, load known items for `root.id`; any known `source_path` not observed is marked `MISSING` unless already missing.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `pytest tests/library/test_scanner.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `feat: scan local video library roots`

---

### Task 4: Existing-file preparation without copying source media

**Files:**
- Modify: `clipatlas/video/frames.py`
- Create: `clipatlas/library/processor.py`
- Test: `tests/library/test_processor.py`
- Modify: `tests/video/test_frames.py` only if constructor coverage is needed.

**Interfaces:**
- Modifies `FrameExtractor.__init__(runner: AsyncCommandRunner | None = None, output_root: Path | None = None)` while preserving existing behavior when `output_root is None`.
- Produces: `LocalFilePreparationService(probe: MediaProbe, scene_detector: SceneDetector, cache_root: Path, runner: AsyncCommandRunner | None = None)`.
- Produces: `prepare(item_id: UUID, source_path: Path, on_stage: Callable[[LibraryItemStatus], None]) -> IngestedVideo`.

- [ ] **Step 1: Write failing processor tests**

Use fake `MediaProbe`, `SceneDetector`, and command runner. Assert:

```python
result = await service.prepare(item_id, source_video, stages.append)
assert stages == [
    LibraryItemStatus.PROBING,
    LibraryItemStatus.SCENE_DETECTION,
    LibraryItemStatus.FRAME_EXTRACTION,
]
assert result.video.source_uri == source_video.resolve().as_uri()
assert source_video.read_bytes() == original_bytes
for frame_uri in result.frames_by_segment.values():
    assert Path(urlparse(frame_uri[0]).path).is_relative_to(cache_root.resolve())
```

Also assert no `frames/` directory is created beside the watched source file.

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest tests/library/test_processor.py -v`
Expected: import failure for `clipatlas.library.processor` or missing `FrameExtractor.output_root` behavior.

- [ ] **Step 3: Refactor FrameExtractor output location**

When `output_root` is set, use:

```python
frame_dir = self._output_root / "frames" / str(segment_id)
```

Otherwise retain current upload behavior:

```python
frame_dir = source.parent / "frames" / str(segment_id)
```

- [ ] **Step 4: Implement LocalFilePreparationService**

Generate a fresh `video_id`, probe source metadata, detect scenes, create existing `VideoAsset`/`VideoSegment` domain objects, and instantiate a cache-scoped `FrameExtractor(output_root=cache_root / str(item_id), runner=runner)`.

Call `on_stage()` immediately before each processing stage. `filename` must be `source_path.name`; `source_uri` must point to the original source path.

- [ ] **Step 5: Verify processor and video regression**

Run: `pytest tests/library/test_processor.py tests/video/test_frames.py tests/video/test_ingest.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

Commit message: `feat: prepare existing library videos in place`

---

### Task 5: Sequential LocalLibraryWorker and failure isolation

**Files:**
- Create: `clipatlas/library/worker.py`
- Test: `tests/library/test_worker.py`

**Interfaces:**
- Consumes: `LibraryStore`, `LocalFilePreparationService`.
- Produces: `LocalLibraryWorker(store: LibraryStore, processor: LocalFilePreparationService)`.
- Produces: `async run_once() -> bool`.
- Produces: `async run_until_empty() -> int`.

- [ ] **Step 1: Write failing worker tests**

Use a real temporary `LibraryStore` plus fake processor.

Assert successful processing:

```python
processed = await worker.run_once()
assert processed is True
item = store.get_item_by_path(movie)
assert item.status is LibraryItemStatus.COMPLETED
assert item.video_id == fake_result.video.id
assert item.processed_fingerprint == item.fingerprint
```

Assert failure isolation by queueing two files, making the first processor call raise `RuntimeError("bad media")`, then calling `run_until_empty()` and verifying first is `FAILED`, second is `COMPLETED`, and the exception did not abort queue draining.

Assert `run_once()` returns `False` when queue is empty.

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest tests/library/test_worker.py -v`
Expected: import failure for worker module.

- [ ] **Step 3: Implement worker**

`run_once()` must:

```python
item = store.claim_next()
if item is None:
    return False
try:
    result = await processor.prepare(
        item.id,
        Path(item.source_path),
        lambda stage: store.set_status(item.id, stage),
    )
except Exception as exc:
    store.fail(item.id, f"{type(exc).__name__}: {exc}"[:2000])
else:
    store.complete(item.id, result.video.id)
return True
```

`run_until_empty()` repeatedly calls `run_once()` and returns number of claimed items.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `pytest tests/library/test_worker.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `feat: add sequential local library worker`

---

### Task 6: Periodic supervisor with restart recovery

**Files:**
- Create: `clipatlas/library/supervisor.py`
- Test: `tests/library/test_supervisor.py`

**Interfaces:**
- Consumes: `LibraryStore`, `LocalFolderScanner`, `LocalLibraryWorker`.
- Produces: `LocalLibrarySupervisor(...)` with:
  - `async start() -> bool`
  - `async stop() -> None`
  - `is_running: bool`
  - `async run_cycle(force_scan: bool = False) -> bool`

Constructor arguments include `scan_interval_seconds: float = 60.0`, `poll_interval_seconds: float = 1.0`, and injectable `clock: Callable[[], float] = time.monotonic`.

- [ ] **Step 1: Write failing supervisor tests**

Use fake scanner/worker and deterministic fake clock. Assert:

- constructor calls `store.recover_interrupted()` exactly once;
- first `run_cycle()` scans immediately;
- another cycle before scan interval processes work without rescanning;
- cycle after interval scans again;
- `start()` returns `True` once and `False` on duplicate start;
- `stop()` is idempotent;
- current item completes before loop exits after stop request.

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest tests/library/test_supervisor.py -v`
Expected: import failure for supervisor module.

- [ ] **Step 3: Implement deterministic cycle and loop**

`run_cycle()` updates next-scan deadline and uses `await asyncio.to_thread(scanner.scan_all)` for filesystem scanning. It then calls one `await worker.run_once()` and returns whether work was processed.

The background loop repeatedly calls `run_cycle()` and, when no work is available, waits using `asyncio.wait_for(stop_event.wait(), timeout=poll_interval_seconds)`. Timeout means continue; stop event means exit.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `pytest tests/library/test_supervisor.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `feat: supervise local library scanning and processing`

---

### Task 7: Runtime wiring and Local Library API

**Files:**
- Create: `clipatlas/library/runtime.py`
- Create: `clipatlas/api/routes/libraries.py`
- Modify: `clipatlas/main.py`
- Modify: `clipatlas/app_state.py`
- Test: `tests/api/test_libraries.py`

**Interfaces:**
- Produces: `LibraryRuntime(store, scanner, worker, supervisor)` dataclass.
- Produces: `build_library_runtime() -> LibraryRuntime` using environment configuration.
- Produces API endpoints exactly as specified in the design.

- [ ] **Step 1: Write failing API tests**

Inject a temporary `LibraryRuntime` into `create_app(library_runtime=runtime)`.

Test:

```python
response = client.post(
    "/api/v1/libraries/roots",
    json={"path": str(media_root), "recursive": True},
)
assert response.status_code == 201

scan = client.post("/api/v1/libraries/scan")
assert scan.status_code == 200
assert scan.json()["discovered"] == 2

status = client.get("/api/v1/libraries/status").json()
assert status["counts"]["QUEUED"] == 2

items = client.get("/api/v1/libraries/items?status=QUEUED&limit=50&offset=0")
assert len(items.json()["items"]) == 2
```

Also test nonexistent root returns 400, retry of non-failed/missing ID returns stable 409/404 behavior, and supervisor start/stop endpoints reflect state.

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest tests/api/test_libraries.py -v`
Expected: 404 because routes do not exist.

- [ ] **Step 3: Implement LibraryRuntime builder**

Read:

```text
CLIPATLAS_LIBRARY_DB=./data/clipatlas-library.sqlite3
CLIPATLAS_LIBRARY_CACHE=./data/library-cache
CLIPATLAS_LIBRARY_SCAN_INTERVAL_SECONDS=60
CLIPATLAS_LIBRARY_POLL_INTERVAL_SECONDS=1
```

Build `LibraryStore`, `LocalFolderScanner`, `LocalFilePreparationService` with existing `MediaProbe`/`SceneDetector`, `LocalLibraryWorker`, and `LocalLibrarySupervisor`.

Do not build the default runtime during unrelated API tests unless a library endpoint is accessed or autorun is explicitly enabled.

- [ ] **Step 4: Implement API routes**

Create request model `CreateLibraryRootRequest(path: str, recursive: bool = True)`.

Use `await asyncio.to_thread(runtime.scanner.scan_all)` for manual scan. Validate `limit` in `1..500` and `offset >= 0`. Serialize status counts using enum values as keys.

- [ ] **Step 5: Wire route and optional autorun**

`create_app()` gains optional `library_runtime: LibraryRuntime | None = None` for tests. Include `libraries_router` without changing existing provider/video route behavior.

When `CLIPATLAS_LIBRARY_AUTORUN=true`, app lifespan builds/starts runtime if needed and stops it on shutdown. With default `false`, no library DB or scanning side effect occurs until a library endpoint is used.

- [ ] **Step 6: Verify API and full regression**

Run: `pytest tests/api/test_libraries.py -v`
Expected: PASS.

Run: `pytest -q`
Expected: all tests PASS.

- [ ] **Step 7: Commit**

Commit message: `feat: expose local library control API`

---

### Task 8: Documentation and final verification

**Files:**
- Modify: `.env.example`
- Modify: `README.md`

**Interfaces:**
- Documents Local Library configuration, API workflow, and no-copy behavior.

- [ ] **Step 1: Update `.env.example`**

Add exactly:

```text
CLIPATLAS_LIBRARY_DB=./data/clipatlas-library.sqlite3
CLIPATLAS_LIBRARY_CACHE=./data/library-cache
CLIPATLAS_LIBRARY_AUTORUN=false
CLIPATLAS_LIBRARY_SCAN_INTERVAL_SECONDS=60
CLIPATLAS_LIBRARY_POLL_INTERVAL_SECONDS=1
```

- [ ] **Step 2: Update README workflow**

Document:

```text
register local folder
-> scan
-> persistent QUEUED items
-> start supervisor
-> sequential ffprobe/shot/frame processing
-> COMPLETED/FAILED
-> restart safely resumes interrupted work
```

Explicitly state originals are read in place and are never copied into ClipAtlas by the Local Library path.

- [ ] **Step 3: Run fresh full verification**

Run: `ruff check .`
Expected: exit 0.

Run: `mypy clipatlas`
Expected: exit 0.

Run: `pytest -v`
Expected: 0 failed.

- [ ] **Step 4: Compare scope to spec**

Verify every in-scope item in `docs/superpowers/specs/2026-09-02-local-library-v0.1.md` has code/tests and that no AI provider calls, UI, PostgreSQL, watchdog, or multi-worker functionality was added.

- [ ] **Step 5: Commit**

Commit message: `docs: document local library workflow`

# ClipAtlas Local Library V0.1 Design

## Goal

Allow ClipAtlas to connect directly to one or more user-selected local folders, discover supported videos without copying the originals, persist processing state, and process the library sequentially in the background with safe restart/resume behavior.

## Scope

This subsystem turns local folders into durable ClipAtlas video sources. It owns discovery, file-state tracking, queue persistence, retry/recovery, and local-file preparation. It does not yet own AI semantic analysis, PostgreSQL/pgvector, browser UI, cloud object storage, or rough-cut generation.

### In scope

1. Register one or more local library roots.
2. Recursively scan supported video extensions.
3. Track files using canonical path + file size + `mtime_ns` fast fingerprint.
4. Persist roots, items, processing status, attempts, errors, processed fingerprint, and produced `video_id` in SQLite.
5. Detect new, unchanged, modified, and missing files.
6. Queue new/modified files automatically; unchanged completed files are skipped.
7. Process one video at a time by default.
8. Continue with the next video when one item fails.
9. Recover interrupted in-flight items to `QUEUED` after restart.
10. Process existing local files in place without copying original media.
11. Store generated frames/cache under ClipAtlas-owned cache directories, never beside the user's source file.
12. Provide a supervisor loop that periodically rescans roots and drains the queue.
13. Provide minimal FastAPI endpoints for root registration, manual scan, queue/status inspection, retry, and supervisor start/stop/status.

### Out of scope

- AI provider calls and semantic annotations.
- PostgreSQL/pgvector migration.
- File-content SHA256 for every source video.
- Real-time filesystem watcher dependency such as watchdog.
- Multi-worker concurrency greater than 1.
- Browser timeline/editor UI.
- Cloud/NAS adapters other than the abstraction points needed for future work.

## Architecture

The flow is:

`LocalLibraryRoot -> LocalFolderScanner -> SQLite LibraryStore -> persistent queue -> LocalLibraryWorker -> LocalFilePreparationService -> ffprobe -> PySceneDetect -> FrameExtractor -> COMPLETED/FAILED`

The supervisor periodically scans enabled roots and then lets a single worker claim queued items one at a time. Source files remain at their original paths. ClipAtlas only writes state and generated artifacts under its own data/cache roots.

## Data model

### `LibraryRoot`

- `id: UUID`
- `path: str` canonical absolute path
- `recursive: bool`
- `enabled: bool`
- `created_at: datetime`

### `LibraryItem`

- `id: UUID`
- `root_id: UUID`
- `source_path: str`
- `size_bytes: int`
- `mtime_ns: int`
- `fingerprint: str`
- `processed_fingerprint: str | None`
- `status: LibraryItemStatus`
- `video_id: UUID | None`
- `attempts: int`
- `last_error: str | None`
- `created_at: datetime`
- `updated_at: datetime`

### `LibraryItemStatus`

- `QUEUED`
- `PROBING`
- `SCENE_DETECTION`
- `FRAME_EXTRACTION`
- `COMPLETED`
- `FAILED`
- `MISSING`

`PROBING`, `SCENE_DETECTION`, and `FRAME_EXTRACTION` are in-flight states. On process startup, any item left in an in-flight state is reset to `QUEUED` so interrupted work can resume.

## Fingerprint policy

V0.1 fast fingerprint is SHA256 over the UTF-8 string:

`<canonical-path>\0<size-bytes>\0<mtime-ns>`

It is not a content hash. It is intentionally cheap for large media libraries. A later optional content-hash layer can be added without changing the queue contract.

`processed_fingerprint` is set only when processing completes successfully. It records exactly which observed file version produced the current `video_id` and generated cache.

## Scan reconciliation rules

For each enabled root:

- supported extension + not previously known -> create item as `QUEUED`;
- known item + same fingerprint -> preserve status;
- known item + changed fingerprint -> clear `video_id`/error/`processed_fingerprint` and set `QUEUED`;
- previously known path not observed in current scan -> set `MISSING`;
- a previously `MISSING` path that reappears -> compare current fingerprint with `processed_fingerprint`; if equal, restore `COMPLETED`, otherwise set `QUEUED`.

Supported extensions for V0.1:

`.mp4`, `.mov`, `.mkv`, `.avi`, `.webm`, `.m4v`

Matching is case-insensitive.

## Persistence

Use Python stdlib `sqlite3` for V0.1 at `CLIPATLAS_LIBRARY_DB`, default `./data/clipatlas-library.sqlite3`.

SQLite is a local-worker persistence mechanism, not the long-term semantic database. Keep access behind `LibraryStore` methods so PostgreSQL can replace it later without changing scanner/worker contracts.

Required database behavior:

- initialize schema idempotently;
- unique canonical `source_path`;
- claim one queued item atomically;
- status transitions persisted immediately;
- attempts increment only when a worker claims an item;
- successful completion stores both `video_id` and `processed_fingerprint`;
- failure stores bounded error text;
- counts by status available without loading every row.

## Existing-file processing

Do not route local-library files through the upload storage copier.

Add a local-file preparation path that reuses current media adapters:

1. generate a ClipAtlas `video_id`;
2. `MediaProbe.probe(source_path)`;
3. `SceneDetector.detect(source_path, duration_ms)`;
4. create canonical `VideoSegment` records;
5. extract representative frames into `CLIPATLAS_LIBRARY_CACHE/<library-item-id>/frames/...`;
6. return `IngestedVideo` referencing the original local source URI.

Default cache root: `./data/library-cache`.

No generated file may be written into the user's watched source directory.

## Worker behavior

`LocalLibraryWorker.run_once()`:

1. atomically claim oldest queued item;
2. increment attempts;
3. mark stage before each expensive operation;
4. process the existing file;
5. on success, store returned `video_id`, copy current `fingerprint` to `processed_fingerprint`, and mark `COMPLETED`;
6. on exception, store a safe error summary and mark `FAILED`;
7. return whether an item was processed.

A failed item never prevents later queued items from running.

Retry is explicit in V0.1: retrying a failed item sets it back to `QUEUED` and clears `last_error`.

## Supervisor behavior

`LocalLibrarySupervisor` owns one async loop with concurrency fixed at 1.

- periodic root rescan interval defaults to 60 seconds;
- queue polling interval defaults to 1 second when idle;
- a scan happens immediately on supervisor start;
- after scan, the worker drains queued work one item at a time;
- stop is cooperative and completes the current item before exiting;
- duplicate `start()` calls are idempotent;
- status reports running/stopped and queue counts.

Environment variables:

- `CLIPATLAS_LIBRARY_DB=./data/clipatlas-library.sqlite3`
- `CLIPATLAS_LIBRARY_CACHE=./data/library-cache`
- `CLIPATLAS_LIBRARY_AUTORUN=false`
- `CLIPATLAS_LIBRARY_SCAN_INTERVAL_SECONDS=60`
- `CLIPATLAS_LIBRARY_POLL_INTERVAL_SECONDS=1`

Autorun defaults to `false` in V0.1 so tests and API startup never begin scanning arbitrary paths unexpectedly. The user can start processing explicitly via API; later desktop packaging can enable autorun by default.

## API surface

### `POST /api/v1/libraries/roots`

Request:

```json
{"path":"D:\\Media","recursive":true}
```

Registers a canonical local directory. Nonexistent/non-directory paths are rejected.

### `GET /api/v1/libraries/roots`

Lists registered roots.

### `POST /api/v1/libraries/scan`

Scans all enabled roots and returns counts for discovered/changed/missing/unchanged items.

### `GET /api/v1/libraries/items`

Lists items with optional `status` filter and bounded pagination.

### `GET /api/v1/libraries/status`

Returns counts by queue status and supervisor state.

### `POST /api/v1/libraries/items/{item_id}/retry`

Moves a failed item back to `QUEUED`.

### `POST /api/v1/libraries/supervisor/start`

Starts periodic scan + sequential processing.

### `POST /api/v1/libraries/supervisor/stop`

Requests cooperative stop.

## Failure and safety model

- user-provided root path is canonicalized and must exist as a directory when registered;
- scanner never follows a path outside the configured root through its own path construction;
- source files are read-only to ClipAtlas;
- generated cache is ClipAtlas-owned;
- per-file processing failures are isolated;
- error messages stored/returned are bounded and must not contain API secrets;
- missing files are state, not fatal errors;
- queue persistence survives process restart.

## Testing strategy

Use temporary directories and a temporary SQLite database. No real user folders, no real AI APIs, and no real media are required in unit tests.

Tests cover:

- extension filtering and recursive scan;
- deterministic fingerprints;
- scan reconciliation for new/unchanged/modified/missing files;
- SQLite persistence across store re-open;
- atomic oldest-item claim and attempt increments;
- interrupted-state recovery;
- sequential worker success/failure/continue behavior;
- local-file preparation writes frames only to cache;
- supervisor idempotent start/stop and periodic scan/queue drain using fake clock/sleep or short injected intervals;
- API registration/scan/status/retry controls;
- existing upload/provider API regression remains green.

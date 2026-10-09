# Video Ingest V0.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add provider-neutral local video ingest that stores uploads, probes media metadata, detects shot boundaries, extracts representative frames, and exposes the result through FastAPI.

**Architecture:** Keep shell/tool interaction behind small adapters and coordinate them in a `VideoIngestService`. Domain-facing time values are integer milliseconds; tests inject fake runners and temporary storage so CI does not require real FFmpeg/PySceneDetect execution.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, httpx, FFmpeg/ffprobe, PySceneDetect, Pytest, Ruff, Mypy.

**Spec:** `docs/superpowers/specs/2026-09-02-video-ingest-v0.1.md`

## Global Constraints

- All ClipAtlas time boundaries are integer milliseconds.
- No API key or secret is involved in this subsystem.
- No arbitrary user-supplied filesystem write path is accepted.
- Tests must not require installed FFmpeg/PySceneDetect binaries or real media files.
- Existing provider contracts and API behavior must remain backward compatible.
- Python remains `>=3.12`.

---

### Task 1: Media metadata contract and ffprobe adapter

**Files:**
- Create: `clipatlas/video/models.py`
- Create: `clipatlas/video/commands.py`
- Create: `clipatlas/video/probe.py`
- Test: `tests/video/test_probe.py`

**Interfaces:**
- Produces: `MediaMetadata(duration_ms: int, width: int, height: int, fps: float, video_codec: str, has_audio: bool)`.
- Produces: `AsyncCommandRunner.run(args: list[str]) -> CommandResult`.
- Produces: `MediaProbe.probe(path: Path) -> MediaMetadata`.

- [ ] **Step 1: Write the failing probe tests**

Test that representative ffprobe JSON parses exact duration milliseconds, dimensions, rational FPS, codec, and audio presence. Test malformed/no-video output raises `MediaProbeError`.

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest tests/video/test_probe.py -v`
Expected: import failure because `clipatlas.video.probe` and models do not exist.

- [ ] **Step 3: Implement minimal command/result and probe parsing**

Use `asyncio.create_subprocess_exec` in the default runner. Run ffprobe with JSON output and parse the first video stream plus optional audio stream. Convert `duration` seconds to rounded integer milliseconds and parse rational FPS such as `30000/1001` safely.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `pytest tests/video/test_probe.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `feat: add ffprobe media metadata adapter`

---

### Task 2: Local video storage

**Files:**
- Create: `clipatlas/video/storage.py`
- Test: `tests/video/test_storage.py`

**Interfaces:**
- Produces: `StoredVideo(video_id: UUID, path: Path, source_name: str)`.
- Produces: `LocalVideoStore.save(video_id: UUID, source_name: str, chunks: AsyncIterator[bytes]) -> StoredVideo`.

- [ ] **Step 1: Write failing storage tests**

Test that storage creates `<root>/<video_uuid>/source.<sanitized-ext>`, streams bytes without trusting path separators in the original name, and defaults unknown extensions to `.bin`.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/video/test_storage.py -v`
Expected: import failure for storage module.

- [ ] **Step 3: Implement minimal streaming storage**

Create directories with `parents=True`, sanitize extension using a strict alphanumeric allowlist, and write chunks with ordinary binary file I/O inside the async method.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/video/test_storage.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `feat: add local video storage`

---

### Task 3: Scene detection adapter and normalization

**Files:**
- Create: `clipatlas/video/scenes.py`
- Test: `tests/video/test_scenes.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `SceneRange(start_ms: int, end_ms: int)`.
- Produces: `SceneDetector.detect(path: Path, duration_ms: int) -> list[SceneRange]`.

- [ ] **Step 1: Write failing scene tests**

Test conversion from detector second ranges to millisecond boundaries, monotonic clamping to duration, removal of zero-length ranges, and fallback `[0, duration_ms]` when no valid ranges exist.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/video/test_scenes.py -v`
Expected: import failure for scene detector.

- [ ] **Step 3: Implement minimal PySceneDetect-backed detector**

Use a small injectable raw detector callable. Production raw detection imports `scenedetect.detect` and `ContentDetector` lazily so unit tests remain independent. Normalize results to ClipAtlas millisecond ranges.

- [ ] **Step 4: Add runtime dependency**

Add `scenedetect>=0.6.6,<0.8` to project dependencies.

- [ ] **Step 5: Verify GREEN**

Run: `pytest tests/video/test_scenes.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

Commit message: `feat: add shot boundary detection`

---

### Task 4: Representative-frame extraction

**Files:**
- Create: `clipatlas/video/frames.py`
- Test: `tests/video/test_frames.py`

**Interfaces:**
- Produces: `representative_timestamps(start_ms: int, end_ms: int) -> list[int]`.
- Produces: `FrameExtractor.extract(source: Path, segment_id: UUID, start_ms: int, end_ms: int) -> list[Path]`.

- [ ] **Step 1: Write failing frame tests**

Test 20/50/80 percent timestamps, de-duplication for very short segments, generated output paths, and exact ffmpeg `-ss` timestamp arguments sent through the injectable command runner.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/video/test_frames.py -v`
Expected: import failure for frame extractor.

- [ ] **Step 3: Implement minimal extraction**

Generate deterministic millisecond timestamps strictly within the segment, create `<source-parent>/frames/<segment_uuid>/frame_000.jpg` style paths, and call ffmpeg once per unique timestamp with one-frame JPEG output.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/video/test_frames.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `feat: extract representative segment frames`

---

### Task 5: Ingest orchestration service

**Files:**
- Create: `clipatlas/video/ingest.py`
- Test: `tests/video/test_ingest.py`

**Interfaces:**
- Produces: `VideoIngestService.ingest(source_name: str, chunks: AsyncIterator[bytes]) -> IngestedVideo`.
- Consumes: `LocalVideoStore`, `MediaProbe`, `SceneDetector`, `FrameExtractor`.

- [ ] **Step 1: Write failing orchestration test**

Test one upload produces a ClipAtlas-owned `VideoAsset`, calls storage/probe/detection in order, materializes one `VideoSegment` per normalized scene range, and maps extracted frame paths by segment UUID.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/video/test_ingest.py -v`
Expected: import failure for ingest service.

- [ ] **Step 3: Implement minimal service**

Generate UUIDs inside ClipAtlas, preserve the original filename only as `VideoAsset.source_name`, set `source_uri` to the stored local URI, and create segments using existing domain models.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/video/test_ingest.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `feat: orchestrate local video ingest`

---

### Task 6: FastAPI upload endpoint

**Files:**
- Create: `clipatlas/api/routes/videos.py`
- Modify: `clipatlas/main.py`
- Modify: `clipatlas/app_state.py`
- Modify: `pyproject.toml`
- Test: `tests/api/test_videos.py`

**Interfaces:**
- Produces: `POST /api/v1/videos` accepting multipart field `file`.
- Returns JSON representation of `IngestedVideo`.

- [ ] **Step 1: Write failing API test**

Inject a fake ingest service into app state, upload `sample.mp4`, and assert status `201`, filename forwarding, response video ID, metadata, segment boundaries, and frame paths.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/api/test_videos.py -v`
Expected: 404 because route does not exist.

- [ ] **Step 3: Implement route and dependency wiring**

Stream `UploadFile` in bounded chunks via an async generator. Add `python-multipart>=0.0.12,<1`. Build the default ingest service from `CLIPATLAS_VIDEO_ROOT` with `./data/videos` default.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/api/test_videos.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `feat: expose video ingest API`

---

### Task 7: Documentation and full verification

**Files:**
- Modify: `.env.example`
- Modify: `README.md`

**Interfaces:**
- Documents `CLIPATLAS_VIDEO_ROOT` and local prerequisites (`ffmpeg`, `ffprobe`).

- [ ] **Step 1: Update configuration documentation**

Document upload endpoint, development storage location, and that PySceneDetect is installed as a Python dependency while FFmpeg binaries must be present in PATH for real local ingest.

- [ ] **Step 2: Run full verification**

Run: `ruff check .`
Run: `mypy clipatlas`
Run: `pytest -v`
Expected: all green.

- [ ] **Step 3: Commit**

Commit message: `docs: document local video ingest`

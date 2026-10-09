# OTIO + Jianying Export V0.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert persisted `RoughCutPlan` revisions into exact-millisecond OpenTimelineIO timelines and export those timelines as editable Jianying drafts through a replaceable `pyJianYingDraft` backend.

**Architecture:** `RoughCutPlan` and its historical `NarrationTrack` remain the only upstream authorities. ClipAtlas first builds and validates an OTIO timeline at rate 1000, then optionally hands that OTIO timeline to a Jianying backend; Jianying-specific code may never call retrieval, TTS, beat building, scoring, or planning services.

**Tech Stack:** Python 3.12, Pydantic 2, FastAPI, SQLite stores already in ClipAtlas, `OpenTimelineIO>=0.18,<0.19`, optional `pyjianyingdraft>=0.3,<0.4`, pytest, Ruff, strict Mypy.

**Spec:** `docs/superpowers/specs/2026-09-03-otio-jianying-export-v0.1-design.md`

## Global Constraints

- OTIO canonical timing rate is exactly `1000`; integer ClipAtlas milliseconds map to integer `RationalTime.value` without frame-rate rounding.
- Jianying conversion is integer `microseconds = milliseconds * 1000`; no floating-point seconds are canonical.
- Export resolves narration with `RoughCutPlan.narration_track_id -> NarrationStore.get_track()`, never `get_active_track()`.
- OTIO export must work even when `pyJianYingDraft` is not installed.
- Jianying adapter consumes OTIO only; it does not import or call semantic retrieval, CandidateScorer, BeatBuilder, NarrationService, SpeechProvider, or RoughCutPlanner.
- V0.1 creates one primary video track and one narration audio track; no transitions, speed changes, BGM, effects, or automatic render.
- Jianying V0.1 supports local `file://` and local filesystem paths only; cloud/HTTP media fail explicitly.
- Jianying Pro 10.8 support must use public `pyJianYingDraft` APIs/codec integration; ClipAtlas must not hardcode encrypted draft internals.
- Export failures must not mutate or delete RoughCutPlan, NarrationTrack, semantic indexes, or previously written OTIO artifacts.

---

## File Structure

Create:

- `clipatlas/exports/__init__.py` — public export-domain surface only.
- `clipatlas/exports/errors.py` — normalized export/Jianying failures.
- `clipatlas/exports/models.py` — OTIO/Jianying settings and returned artifact models.
- `clipatlas/exports/contracts.py` — replaceable `JianyingBackend` protocol.
- `clipatlas/exports/otio.py` — pure RoughCutPlan + NarrationTrack to OTIO conversion, validation, serialization/read-back.
- `clipatlas/exports/jianying.py` — `pyJianYingDraft` backend and OTIO-to-Jianying mapping only.
- `clipatlas/exports/service.py` — persisted-plan/historical-narration resolution and export orchestration.
- `clipatlas/api/routes/exports.py` — OTIO/Jianying HTTP endpoints.
- `tests/exports/test_otio.py` — exact timing and OTIO serialization tests.
- `tests/exports/test_service.py` — history resolution/failure isolation tests.
- `tests/exports/test_jianying.py` — pure Jianying mapping/backend tests.
- `tests/api/test_exports.py` — API/error-code contract.
- `tests/integration/test_export_pipeline.py` — RoughCutStore + NarrationStore + export end-to-end invariant.
- `docs/otio-jianying-export-v0.1.md` — Chinese operational documentation.

Modify:

- `pyproject.toml` — OTIO core dependency, optional Jianying extra, CI/dev Jianying dependency.
- `.env.example` — export root and Jianying configuration.
- `clipatlas/app_state.py` — export runtime builder and optional Jianying backend injection.
- `clipatlas/api/errors.py` — stable export error codes.
- `clipatlas/main.py` — runtime wiring and export router.
- `README.md` — mark D V0.1 complete and document endpoints/configuration after final GREEN.

---

### Task 1: Exact OTIO Timeline Builder

**Files:**
- Modify: `pyproject.toml`
- Create: `clipatlas/exports/errors.py`
- Create: `clipatlas/exports/otio.py`
- Create: `clipatlas/exports/__init__.py`
- Test: `tests/exports/test_otio.py`

**Interfaces:**
- Consumes: `RoughCutPlan`, `RoughCutClip`, `NarrationTrack`.
- Produces: `class OtioTimelineBuilder` with `build(plan: RoughCutPlan, narration: NarrationTrack) -> otio.schema.Timeline`.
- Produces errors: `TimelineExportError`, `ExportNotReadyError`, `ExportInvariantError`, `OtioSerializationError`.

- [ ] **Step 1: Write RED tests for exact 1000-rate video and narration mapping**

Create a real `RoughCutPlan` with two contiguous clips, e.g. `0..1250 ms` and `1250..3000 ms`, using non-zero source ranges such as `83420..84670 ms`. Create the matching historical `NarrationTrack` with `duration_ms=3000` and a local `audio_uri`.

Assert:

```python
timeline = OtioTimelineBuilder().build(plan, narration)
video_track = timeline.video_tracks()[0]
audio_track = timeline.audio_tracks()[0]

first = video_track[0]
assert first.source_range.start_time.value == 83420
assert first.source_range.start_time.rate == 1000
assert first.source_range.duration.value == 1250
assert first.source_range.duration.rate == 1000
assert first.media_reference.target_url == plan.clips[0].source_uri
assert first.metadata["clipatlas"]["timeline_in_ms"] == 0
assert first.metadata["clipatlas"]["timeline_out_ms"] == 1250

narration_clip = audio_track[0]
assert narration_clip.source_range.start_time.value == 0
assert narration_clip.source_range.duration.value == 3000
assert narration_clip.media_reference.target_url == narration.audio_uri
assert timeline.duration().value == 3000
assert timeline.duration().rate == 1000
assert timeline.metadata["clipatlas"]["plan_id"] == str(plan.id)
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
pytest tests/exports/test_otio.py -v
```

Expected: collection/import failure because `clipatlas.exports.otio` does not exist. Fix only test syntax/import ordering until the failure is specifically the missing production export module.

- [ ] **Step 3: Implement the minimal OTIO builder**

Add `opentimelineio>=0.18,<0.19` to normal dependencies.

Use exactly:

```python
_TIME_RATE = 1000

def _rt(ms: int) -> otio.opentime.RationalTime:
    return otio.opentime.RationalTime(ms, _TIME_RATE)
```

Create one `otio.schema.Track(kind=otio.schema.TrackKind.Video)` and one audio track. Each `RoughCutClip` becomes `otio.schema.Clip` with an `ExternalReference(target_url=source_uri)` and a `source_range` whose start/duration are integer milliseconds at rate 1000. Store all ClipAtlas IDs/scores/reasons under `clip.metadata["clipatlas"]`.

- [ ] **Step 4: Add RED invariant tests, then implement validation**

Each separate test must fail for exactly one condition:

```text
no plan clips
first timeline_in_ms != 0
gap/overlap between adjacent destination clips
final timeline_out_ms != plan.total_duration_ms
source duration != destination duration
empty source_uri
narration project mismatch
missing narration audio_uri
narration duration != plan.total_duration_ms
```

Raise `ExportInvariantError` for plan/timeline structural corruption and `ExportNotReadyError` for missing/mismatched narration media readiness.

- [ ] **Step 5: Run focused GREEN and commit**

Run:

```bash
ruff check clipatlas/exports tests/exports/test_otio.py
mypy clipatlas/exports
pytest tests/exports/test_otio.py -v
```

Commit only after all three pass.

---

### Task 2: Native `.otio` Serialization and Read-Back Verification

**Files:**
- Create: `clipatlas/exports/models.py`
- Modify: `clipatlas/exports/otio.py`
- Test: `tests/exports/test_otio.py`

**Interfaces:**
- Consumes: `OtioTimelineBuilder.build(...)`.
- Produces: `OtioExportArtifact` and `OtioTimelineBuilder.write_verified(timeline, output_path, *, plan_id, project_id, narration_track_id) -> OtioExportArtifact`.

- [ ] **Step 1: Write RED round-trip serialization test**

Write the timeline to a temporary path, then assert the returned artifact path exists and a fresh `otio.adapters.read_from_file()` preserves:

```text
plan_id/project_id/narration_track_id
rough_cut_revision/narration_revision
total_duration_ms/timing_rate=1000
first video source start/duration
video total duration
audio narration duration
```

- [ ] **Step 2: Verify RED specifically for missing `write_verified`**

Run the single test and ensure it fails because the method/model is absent, not because test fixtures are invalid.

- [ ] **Step 3: Implement write + read-back verification using OTIO adapters**

Use:

```python
otio.adapters.write_to_file(timeline, str(output_path))
roundtrip = otio.adapters.read_from_file(str(output_path))
```

Create parent directories first. Convert adapter/read-back failures to `OtioSerializationError`. Never handwrite `.otio` JSON.

- [ ] **Step 4: Add malformed/empty write failure coverage**

Use a monkeypatch only at the external adapter boundary to force write/read failure; assert normalized `OtioSerializationError` and that upstream objects are unchanged.

- [ ] **Step 5: Run focused GREEN and commit**

Run Ruff, Mypy, and `pytest tests/exports/test_otio.py -v`.

---

### Task 3: TimelineExportService and Historical Narration Resolution

**Files:**
- Create: `clipatlas/exports/service.py`
- Modify: `clipatlas/exports/models.py`
- Test: `tests/exports/test_service.py`

**Interfaces:**
- Consumes: `RoughCutStore.get_plan(plan_id)`, `NarrationStore.get_track(track_id)`, `OtioTimelineBuilder`.
- Produces:

```python
class TimelineExportService:
    def export_otio(self, plan_id: UUID) -> OtioExportArtifact: ...
    def export_jianying(
        self,
        plan_id: UUID,
        *,
        draft_name: str,
        settings: JianyingExportSettings,
    ) -> JianyingDraftArtifact: ...
```

`export_jianying` may initially raise `JianyingUnavailableError` until Task 5 supplies the backend.

- [ ] **Step 1: Write RED test proving historical track lookup**

Persist narration revision 1 and revision 2 for one project; make revision 2 active, but persist a RoughCutPlan that references revision 1. Export plan 1 and assert the OTIO audio clip uses revision 1 URI/duration. This test must fail if implementation ever calls `get_active_track()`.

- [ ] **Step 2: Write RED missing-plan and missing-track tests**

Missing plan -> `ExportPlanNotFoundError`; missing referenced narration -> `ExportNotReadyError`.

- [ ] **Step 3: Implement service and canonical output path**

Default path:

```text
<export_root>/<project_id>/<plan_id>/roughcut-r<revision>.otio
```

The service must not rewrite the plan or activate another narration track.

- [ ] **Step 4: Verify stored objects are byte/model-equivalent before/after export**

Read the same plan and narration again after success/failure and assert equality.

- [ ] **Step 5: Run focused GREEN and commit**

Run Ruff/Mypy plus service and OTIO tests.

---

### Task 4: Jianying-Neutral Contract, Settings, URI and Time Mapping

**Files:**
- Create: `clipatlas/exports/contracts.py`
- Modify: `clipatlas/exports/models.py`
- Create: `clipatlas/exports/jianying.py`
- Test: `tests/exports/test_jianying.py`

**Interfaces:**
- Produces:

```python
class JianyingBackend(Protocol):
    name: str
    version: str
    def export(
        self,
        timeline: otio.schema.Timeline,
        *,
        draft_name: str,
        settings: JianyingExportSettings,
    ) -> JianyingDraftArtifact: ...
```

- Produces `JianyingMode.PORTABLE` and `JianyingMode.JIANYING_PRO_10_8`.
- Produces pure helpers for OTIO ms -> Jianying µs and local media-path resolution.

- [ ] **Step 1: Write RED tests for exact integer microsecond conversion**

Examples:

```python
assert _otio_time_to_us(RationalTime(83420, 1000)) == 83_420_000
assert _otio_time_to_us(RationalTime(5750, 1000)) == 5_750_000
```

Reject non-integral millisecond results rather than silently rounding.

- [ ] **Step 2: Write RED tests for local URI resolution**

Support `file:///...` and already-local paths. Reject `https://`, `http://`, `s3://` with `JianyingMediaError`.

- [ ] **Step 3: Implement settings validation**

`width > 0`, `height > 0`. `jianying_pro_10_8` requires explicit draft/install/user-data paths demanded by the backend configuration. Normalize paths without touching retrieval/planning state.

- [ ] **Step 4: Add structural test that `jianying.py` has no forbidden upstream imports**

Read the source text/AST and assert it does not import:

```text
clipatlas.search
clipatlas.roughcut.planner
clipatlas.roughcut.scoring
clipatlas.speech.service
clipatlas.speech.providers
```

- [ ] **Step 5: Run focused GREEN and commit**

---

### Task 5: `pyJianYingDraft` Portable Backend

**Files:**
- Modify: `pyproject.toml`
- Modify: `clipatlas/exports/jianying.py`
- Modify: `clipatlas/exports/service.py`
- Test: `tests/exports/test_jianying.py`
- Test: `tests/exports/test_service.py`

**Interfaces:**
- Produces `PyJianYingDraftBackend` implementing `JianyingBackend`.
- Dependency extra:

```toml
jianying = ["pyjianyingdraft>=0.3,<0.4"]
```

Development extra also includes the same package so CI exercises portable draft generation.

- [ ] **Step 1: Write RED backend test from a real OTIO timeline**

Create temporary local placeholder media files sufficient for the library's metadata expectations, or use the smallest generated valid media fixtures already available in repository tests. Export portable draft and assert:

```text
draft folder exists
one primary video track exists
video segments preserve OTIO order
source_timerange starts/durations equal OTIO source ranges in µs
one narration audio segment starts at 0 and spans total duration
no BGM track is created
artifact plan_id and duration come from OTIO metadata
```

- [ ] **Step 2: Verify RED for missing backend implementation**

- [ ] **Step 3: Implement only public pyJianYingDraft APIs**

Use the verified 0.3.x public surface:

```python
folder = draft.DraftFolder(str(settings.draft_root))
script = folder.create_draft(draft_name, settings.width, settings.height, allow_replace=True)
script.append_tracks([
    draft.TrackSpec(draft.TrackType.video, "main_video"),
    draft.TrackSpec(draft.TrackType.audio, "narration"),
])
video = draft.VideoSegment(path, target_timerange, source_timerange=source_timerange)
audio = draft.AudioSegment(path, target_timerange)
script.add_segment(video, "main_video")
script.add_segment(audio, "narration")
script.save()
```

Do not create transitions/effects/BGM/speed changes.

- [ ] **Step 4: Normalize dependency/write failures**

Absent import -> `JianyingDependencyError`; unsupported media -> `JianyingMediaError`; create/save errors -> `JianyingWriteError`.

- [ ] **Step 5: Run focused GREEN and commit**

---

### Task 6: Runtime Configuration and Optional Jianying Injection

**Files:**
- Modify: `.env.example`
- Modify: `clipatlas/app_state.py`
- Test: `tests/test_export_app_state.py`

**Interfaces:**
- Produces `ExportRuntime` containing `service`, `otio_builder`, and optional `jianying_backend`.
- Produces `build_export_runtime(rough_cut_store, narration_store) -> ExportRuntime`.

- [ ] **Step 1: Write RED runtime tests**

Assert OTIO runtime is always created. Assert missing optional Jianying dependency does not stop application/runtime creation and results in backend `None` or normalized unavailable state. Assert `CLIPATLAS_EXPORT_ROOT` overrides default.

- [ ] **Step 2: Write RED `jianying_pro_10_8` configuration test**

Missing required local paths must only disable/fail Jianying configuration, not OTIO export capability.

- [ ] **Step 3: Implement environment parsing and safe injection**

Add:

```text
CLIPATLAS_EXPORT_ROOT=./data/exports
CLIPATLAS_JIANYING_DRAFT_ROOT=
CLIPATLAS_JIANYING_INSTALL_DIR=
CLIPATLAS_JIANYING_USER_DATA=
CLIPATLAS_JIANYING_MODE=portable
```

No API key or unrelated provider settings belong in this runtime.

- [ ] **Step 4: Run focused GREEN and commit**

---

### Task 7: Export API and Stable Errors

**Files:**
- Create: `clipatlas/api/routes/exports.py`
- Modify: `clipatlas/api/errors.py`
- Modify: `clipatlas/main.py`
- Test: `tests/api/test_exports.py`

**Interfaces:**

```text
POST /api/v1/exports/otio
POST /api/v1/exports/jianying
```

- [ ] **Step 1: Write RED OTIO API tests**

Request:

```json
{"plan_id":"<uuid>"}
```

Success returns `OtioExportArtifact`. Missing plan returns 404 code `export_plan_not_found`. Missing historical narration/audio returns 409 code `export_not_ready`. Invariant/write failures map to their stable 500 codes.

- [ ] **Step 2: Write RED Jianying API tests**

Request includes `plan_id`, `draft_name`, width/height/mode and optional configured paths. Validate:

```text
503 jianying_unavailable
503 jianying_dependency_missing
409 jianying_not_configured
422 jianying_media_unsupported
500 jianying_write_failed
```

- [ ] **Step 3: Implement routes/error handlers/runtime state wiring**

Routes call only `TimelineExportService`; no route directly reads RoughCutStore/NarrationStore or imports pyJianYingDraft.

- [ ] **Step 4: Run focused GREEN and commit**

---

### Task 8: End-to-End Export Invariant, Chinese Docs, Full CI, Non-Draft PR

**Files:**
- Create: `tests/integration/test_export_pipeline.py`
- Create: `docs/otio-jianying-export-v0.1.md`
- Modify: `README.md`

**Interfaces:**
- Verifies the complete D boundary without rerunning A/B/C.

- [ ] **Step 1: Write integration test using real stores and real OTIO**

Persist:

```text
historical NarrationTrack
RoughCutPlan referencing that exact track
```

Run `TimelineExportService.export_otio()`, read `.otio` back, and assert exact plan IDs, source ranges, narration URI, and total duration. Then run Jianying portable export against temporary valid local media and assert editable draft structure is created.

- [ ] **Step 2: Add failure-isolation integration test**

Force Jianying backend failure after a valid `.otio` exists; assert `.otio`, plan, and narration remain unchanged and a retry does not call any planner/TTS/retrieval component.

- [ ] **Step 3: Update Chinese documentation**

Document exact chain:

```text
RoughCutPlan -> OTIO -> Jianying Adapter -> editable draft
```

Explain OTIO 1000-rate milliseconds, supported local media, portable vs Jianying Pro 10.8 mode, optional dependency behavior, environment variables, API usage, and that V0.1 does not launch/render Jianying.

- [ ] **Step 4: Run final repository verification**

Run the repository CI-equivalent suite:

```bash
ruff check .
mypy clipatlas
pytest -v
```

No skipped full-regression claim is acceptable.

- [ ] **Step 5: Open non-draft PR and require fresh PR-triggered CI**

PR head must be the exact final verified branch head. Merge only when PR-triggered Install/Ruff/Mypy/Pytest are all success and GitHub reports the PR mergeable. Merge using expected head SHA.

---

## Self-Review

- Spec coverage: exact historical narration, OTIO rate 1000, serialization/read-back, Jianying optional backend, portable/10.8 configuration, local media-only rule, stable API errors, runtime degradation, failure isolation, docs, and fresh PR CI are all assigned to explicit tasks.
- Placeholder scan: no TBD/TODO/"similar to" instructions remain.
- Type consistency: `OtioTimelineBuilder`, `TimelineExportService`, `JianyingBackend`, `JianyingExportSettings`, `OtioExportArtifact`, and `JianyingDraftArtifact` names are consistent across tasks.
- Boundary consistency: only service resolves stores; only OTIO builder sees RoughCutPlan/NarrationTrack; Jianying backend receives OTIO only.

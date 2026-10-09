# ClipAtlas OTIO + Jianying Export V0.1 Design

## Goal

Implement subproject D of the approved Script-Driven Rough-Cut architecture:

```text
RoughCutPlan
→ OpenTimelineIO
→ Jianying / 剪映 Adapter
→ editable Jianying draft
```

This layer is an **export boundary**, not another planning layer. It must preserve the exact source/timeline decisions already made by `RoughCutPlan`, include the exact narration track used by that historical plan, and isolate Jianying format/version failures from all upstream data.

## Current upstream authority

The exporter must reuse existing canonical objects without copying or re-deriving them:

- `RoughCutStore.get_plan(plan_id)` resolves the exact persisted rough-cut revision.
- `RoughCutPlan.clips[]` owns exact source and destination millisecond ranges.
- `RoughCutPlan.narration_track_id` identifies the exact narration revision used during planning.
- `NarrationStore.get_track(track_id)` resolves that historical narration track, not merely the project's current active narration.
- `NarrationTrack.audio_uri` and `duration_ms` own the narration media reference and duration.

Export must never re-run retrieval, reranking, beat decomposition, TTS, alignment, or rough-cut planning.

---

# 1. Architecture decisions

## 1.1 OTIO is the stable interchange boundary

ClipAtlas core exports a native OpenTimelineIO timeline before any NLE-specific adapter runs.

V0.1 uses:

```text
OpenTimelineIO >=0.18,<0.19
```

The native `.otio` file is the reusable canonical interchange artifact for downstream NLE adapters.

Why this boundary exists:

- Jianying draft structure is version-specific.
- Future Premiere / Resolve / Final Cut adapters must not require planner changes.
- A Jianying incompatibility must not invalidate a valid RoughCutPlan or OTIO file.

## 1.2 Exact millisecond preservation uses OTIO rate = 1000

ClipAtlas canonical timing is integer milliseconds. V0.1 therefore represents all OTIO `RationalTime` values at:

```text
rate = 1000
value = integer milliseconds
```

Examples:

```text
83420 ms → RationalTime(83420, 1000)
5750 ms  → RationalTime(5750, 1000)
```

This avoids introducing 24/25/30 fps rounding into a system whose current authoritative edit clock is narration milliseconds.

The later Jianying adapter converts integer milliseconds to integer microseconds exactly:

```text
1 ms = 1000 µs
```

Frame-rate-aware final rendering remains outside V0.1.

## 1.3 Jianying is a replaceable optional backend

The core package must not hardcode `draft_content.json` internals or implement Jianying encryption itself.

Define a provider-neutral export contract:

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

First real backend:

```text
pyJianYingDraft >=0.3,<0.4
```

It is an optional dependency and a replaceable implementation detail.

## 1.4 Supported Jianying target

V0.1 targets the capabilities exposed by `pyJianYingDraft 0.3.x`, including its Jianying Pro 10.8 local-draft support path.

Two execution modes are distinguished:

### `portable`

- no Jianying installation required;
- creates a pyJianYingDraft draft structure using its normal draft APIs;
- usable for cross-platform CI, structural verification, and compatible plaintext workflows;
- does not claim compatibility with every encrypted high-version Jianying installation.

### `jianying_pro_10_8`

- intended for real local Jianying Pro 10.8 draft generation;
- requires a configured Jianying draft root;
- requires configured Jianying installation directory and user-data directory when the library codec requires them;
- uses `pyJianYingDraft`'s codec/backend rather than ClipAtlas implementing encryption or reverse-engineering draft internals.

If required local Jianying resources are absent, export fails with a normalized Jianying configuration error. RoughCutPlan and OTIO remain valid.

## 1.5 No automatic GUI/render control in D V0.1

V0.1 produces an editable draft folder. It does not require:

- launching Jianying;
- clicking UI controls;
- automatic final video render/export;
- Windows desktop automation.

Those can be separate future capabilities.

---

# 2. Package layout

Create:

```text
clipatlas/exports/
├── __init__.py
├── errors.py
├── models.py
├── contracts.py
├── otio.py
├── jianying.py
└── service.py
```

Responsibilities:

- `models.py`: export settings/artifact models only.
- `errors.py`: normalized export failures.
- `contracts.py`: replaceable Jianying backend protocol.
- `otio.py`: pure `RoughCutPlan + NarrationTrack → OTIO Timeline` conversion and `.otio` serialization.
- `jianying.py`: pyJianYingDraft adapter only; no planning/retrieval logic.
- `service.py`: resolve persisted plan + exact historical narration track, build OTIO, isolate/export artifacts.

API/runtime additions remain outside the package:

```text
clipatlas/app_state.py
clipatlas/api/errors.py
clipatlas/api/routes/exports.py
clipatlas/main.py
```

---

# 3. Canonical export models

## 3.1 `ExportKind`

```text
otio
jianying
```

## 3.2 `OtioExportArtifact`

Required fields:

- `plan_id`
- `project_id`
- `narration_track_id`
- `output_path`
- `timeline_duration_ms`
- `created_at`

The file is a native `.otio` JSON timeline.

## 3.3 `JianyingMode`

```text
portable
jianying_pro_10_8
```

## 3.4 `JianyingExportSettings`

Required fields:

- `draft_root: Path`
- `width: int = 1920`
- `height: int = 1080`
- `mode: JianyingMode = portable`
- optional `jianying_install_dir`
- optional `jianying_user_data_path`

Validation:

- width/height > 0;
- `jianying_pro_10_8` requires all paths needed by the codec/backend;
- paths are normalized locally;
- no arbitrary retrieval/planning parameters exist here.

## 3.5 `JianyingDraftArtifact`

Required fields:

- `backend`
- `backend_version`
- `draft_name`
- `draft_path`
- `plan_id` (copied from OTIO timeline metadata by the service/backend boundary)
- `timeline_duration_ms`
- `created_at`

---

# 4. OTIO timeline mapping

## 4.1 Timeline metadata

Create one `otio.schema.Timeline` with metadata namespace `clipatlas` containing at minimum:

```text
plan_id
project_id
narration_track_id
narration_revision
rough_cut_revision
total_duration_ms
timing_rate = 1000
```

Do not use NLE-specific metadata as canonical identity.

## 4.2 Video track

Create exactly one primary OTIO video track in V0.1.

For every `RoughCutClip` in destination timeline order:

1. Create `ExternalReference(target_url=source_uri)`.
2. Set media `available_range` to the selected canonical source interval.
3. Create an OTIO `Clip` whose `source_range` is exactly:

```text
start_time = source_in_ms @ 1000
 duration  = source_out_ms - source_in_ms @ 1000
```

4. Preserve ClipAtlas metadata:

```text
beat_id
segment_id
video_id
source_in_ms
source_out_ms
timeline_in_ms
timeline_out_ms
score
score_breakdown
selection_reason
```

5. Do not insert gaps or transitions in V0.1.

The sequential OTIO video-track duration must equal `RoughCutPlan.total_duration_ms` exactly.

## 4.3 Narration audio track

Create one OTIO audio track containing exactly one narration clip:

- `ExternalReference(target_url=NarrationTrack.audio_uri)`;
- source start 0 ms;
- duration exactly `NarrationTrack.duration_ms`;
- ClipAtlas narration metadata including track ID/revision/source mode/timing quality.

The narration clip starts at destination time 0.

## 4.4 Historical narration consistency

Export service resolves the exact track by:

```text
plan.narration_track_id
→ NarrationStore.get_track(...)
```

It must **not** use `get_active_track(project_id)` because the active narration may have changed after the historical rough cut was created.

Validate:

- track exists;
- track.project_id == plan.project_id;
- `audio_uri` exists/non-empty;
- `track.duration_ms == plan.total_duration_ms`.

Mismatch raises an export-not-ready error instead of silently stretching or truncating audio.

---

# 5. OTIO validation and serialization

## 5.1 Converter invariants

Before returning an OTIO timeline:

- plan has at least one clip;
- first rough-cut destination starts at 0;
- final rough-cut destination ends at total duration;
- adjacent rough-cut clips are contiguous;
- each source duration equals destination duration;
- source URI is non-empty;
- narration duration equals plan duration.

The converter does not repair invalid plans. Upstream invalid data raises `ExportInvariantError`.

## 5.2 Native `.otio` serialization

Use OTIO's adapter API, not handwritten JSON:

```python
otio.adapters.write_to_file(timeline, output_path)
```

After writing, V0.1 reads the file back through OTIO and re-validates essential metadata/timing before returning success.

This prevents returning a successful artifact for a malformed/empty output file.

## 5.3 Output naming

Default export root:

```text
CLIPATLAS_EXPORT_ROOT=./data/exports
```

Default OTIO file path:

```text
<export-root>/<project_id>/<plan_id>/roughcut-r<revision>.otio
```

Parent directories are created automatically.

Historical exports are not required to overwrite each other.

---

# 6. Jianying-neutral mapping boundary

The Jianying adapter receives OTIO, not RoughCutPlan.

Before calling a backend, the service validates the OTIO timeline includes:

- one non-empty video track;
- one narration audio track;
- ClipAtlas plan metadata;
- exact total duration.

The backend extracts only NLE-facing information from OTIO:

```text
video target_url
video source range
video sequential timeline placement
narration target_url
narration source range
project/plan metadata
```

It must not access:

- SemanticSearchService;
- CandidateScorer;
- BeatBuilder;
- NarrationService/TTS provider;
- RoughCutPlanner.

This separation is tested structurally.

---

# 7. pyJianYingDraft adapter

## 7.1 Dependency isolation

`pyjianyingdraft>=0.3,<0.4` is exposed through an optional project extra:

```toml
[project.optional-dependencies]
jianying = ["pyjianyingdraft>=0.3,<0.4"]
```

Development CI also installs the tested Jianying dependency so the adapter's pure draft-generation behavior is exercised.

If the optional dependency is absent in a normal installation, importing ClipAtlas core still works. Calling Jianying export raises `JianyingDependencyError`.

## 7.2 Time conversion

Jianying adapter converts OTIO 1000-rate values to integer microseconds with exact arithmetic.

No floating-point seconds are used as canonical conversion.

Conceptually:

```text
start_us = start_ms * 1000
duration_us = duration_ms * 1000
```

## 7.3 Video segment mapping

For each OTIO video clip:

- resolve local media path from `file://` URI or supported local path form;
- destination range follows sequential OTIO placement;
- `source_timerange` uses OTIO source start/duration;
- add to one primary Jianying video track in OTIO order.

No transition/effect/speed change is added in V0.1.

## 7.4 Narration mapping

Narration OTIO audio clip becomes one Jianying audio segment:

- starts at destination 0;
- duration equals complete timeline duration;
- uses exact narration media path;
- no BGM is created.

## 7.5 Draft creation

Portable mode uses pyJianYingDraft's public draft-folder/script/segment APIs.

Jianying Pro 10.8 mode uses pyJianYingDraft's public crypto/configuration APIs when configured. ClipAtlas does not manipulate encrypted draft JSON directly.

Draft name is sanitized only for filesystem-invalid characters; the user-visible requested name otherwise remains intact.

## 7.6 Unsupported media URI

V0.1 Jianying adapter supports local media only:

- `file:///...`
- normalized local filesystem paths when already provided as local paths.

HTTP/S3/cloud-only media references raise `JianyingMediaError` rather than downloading implicitly.

---

# 8. Export service and failure isolation

Create `TimelineExportService` consuming:

- `RoughCutStore`
- `NarrationStore`
- `OtioTimelineBuilder`
- optional `JianyingBackend`
- export root

Primary operations:

```python
export_otio(plan_id: UUID) -> OtioExportArtifact
export_jianying(
    plan_id: UUID,
    *,
    draft_name: str,
    settings: JianyingExportSettings,
) -> JianyingDraftArtifact
```

Flow for OTIO:

```text
get persisted RoughCutPlan
→ get exact historical NarrationTrack
→ validate export inputs
→ build OTIO timeline
→ serialize .otio
→ read-back verify
→ return artifact
```

Flow for Jianying:

```text
get persisted RoughCutPlan
→ get exact historical NarrationTrack
→ build/validate OTIO timeline in memory
→ call replaceable Jianying backend
→ return draft artifact
```

A Jianying failure never mutates/deletes:

- RoughCutPlan;
- NarrationTrack;
- generated `.otio` artifact;
- semantic index.

Retrying Jianying export does not rerun upstream AI/TTS/planning.

---

# 9. Errors

Create normalized hierarchy:

```text
TimelineExportError
├── ExportNotReadyError
├── ExportPlanNotFoundError
├── ExportInvariantError
├── OtioSerializationError
├── JianyingUnavailableError
├── JianyingDependencyError
├── JianyingConfigurationError
├── JianyingMediaError
└── JianyingWriteError
```

API mapping recommendation:

- 404 `export_plan_not_found`
- 409 `export_not_ready`
- 500 `export_invariant_failed`
- 500 `otio_serialization_failed`
- 503 `jianying_unavailable`
- 503 `jianying_dependency_missing`
- 409 `jianying_not_configured`
- 422 `jianying_media_unsupported`
- 500 `jianying_write_failed`

Messages remain human-readable; clients depend on stable codes.

---

# 10. Runtime configuration

Add:

```text
CLIPATLAS_EXPORT_ROOT=./data/exports
CLIPATLAS_JIANYING_DRAFT_ROOT=
CLIPATLAS_JIANYING_INSTALL_DIR=
CLIPATLAS_JIANYING_USER_DATA=
CLIPATLAS_JIANYING_MODE=portable
```

Runtime always constructs OTIO export capability.

Jianying backend rules:

- optional dependency absent → backend unavailable, core app still starts;
- portable mode + dependency installed → backend available with configured/default export root;
- `jianying_pro_10_8` requires explicit local paths; missing paths make only Jianying export unavailable/not configured.

---

# 11. API

Add:

```text
POST /api/v1/exports/otio
POST /api/v1/exports/jianying
```

## OTIO request

```json
{
  "plan_id": "uuid"
}
```

Response returns `OtioExportArtifact`.

## Jianying request

V0.1 request fields:

```json
{
  "plan_id": "uuid",
  "draft_name": "ClipAtlas Rough Cut",
  "width": 1920,
  "height": 1080
}
```

Mode/installation paths are runtime configuration rather than arbitrary request-controlled paths.

This makes desktop UI configuration explicit and avoids exposing unrestricted filesystem destinations through normal API requests.

---

# 12. Acceptance criteria

OTIO + Jianying Export V0.1 is complete when tests prove:

1. exact `RoughCutPlan` source ranges become OTIO clip source ranges at rate 1000;
2. OTIO video-track duration exactly equals `plan.total_duration_ms`;
3. exact historical `NarrationTrack`, not current active narration, becomes the OTIO audio track;
4. narration audio duration exactly matches visual timeline duration;
5. `.otio` file can be written and read back without losing ClipAtlas IDs or millisecond ranges;
6. Jianying adapter depends only on OTIO/export settings, not retrieval/planner services;
7. OTIO millisecond timing converts to exact Jianying microseconds;
8. video source trims and narration timing are preserved in generated draft data;
9. no BGM, transition, effect, or speed change is invented;
10. unsupported remote media fails explicitly;
11. missing pyJianYingDraft does not prevent ClipAtlas core/OTIO startup;
12. Jianying Pro 10.8 mode validates required local codec paths before writing;
13. Jianying write/config/version failure leaves persisted RoughCutPlan usable and OTIO export retryable;
14. API can export OTIO and request Jianying draft generation with stable normalized errors;
15. a fake second NLE backend can consume the OTIO boundary without any RoughCutPlanner change;
16. Ruff, strict Mypy, full Pytest, and fresh PR CI all pass.

---

# 13. Explicit non-goals

Not in D V0.1:

- automatic Jianying GUI control;
- final video rendering;
- captions/subtitles;
- BGM;
- transitions/effects/color grading;
- speed ramps;
- optical flow;
- proxy generation;
- cloud media download;
- direct Premiere/Resolve/FCP adapters;
- handwritten Jianying encryption/decryption;
- embedding/retrieval/reranking changes;
- re-running TTS/alignment/planning during export.

The output of this subproject is an exact, reusable OTIO timeline plus a replaceable Jianying draft export path.
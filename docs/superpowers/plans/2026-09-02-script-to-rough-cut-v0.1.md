# ClipAtlas Script-to-Rough-Cut V0.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the canonical automatic rough-cut planner that turns ClipAtlas's active timed narration plus semantic retrieval results into a deterministic, persisted `RoughCutPlan` with exact source and destination time ranges.

**Architecture:** The planner reads the already-canonical `NarrationTrack`/`NarrationUnit` clock and the existing `SemanticSearchService` result contract. `BeatBuilder` owns destination timing, `CandidateScorer` owns deterministic reranking, `RoughCutPlanner` owns source selection/duration filling, and `RoughCutStore` owns plan revisions. This plan implements subproject C only; OTIO and Jianying/剪映 remain subproject D.

**Tech Stack:** Python 3.12, Pydantic 2, FastAPI, SQLite, pytest, Ruff, strict Mypy.

**Spec:** `docs/superpowers/specs/2026-09-02-script-to-rough-cut-v0.1-design.md`

## Global Constraints

- Real narration timing is authoritative whenever an active real narration track exists.
- V0.1 automatic rough cut requires timed narration units; `TRACK_ONLY` and `ESTIMATED` tracks are rejected.
- Beat windows and output clips must cover `0..NarrationTrack.duration_ms` without destination gaps or overlaps.
- Selected source ranges may trim only inside `SemanticSearchHit.source_start_ms..source_end_ms`.
- Every beat performs Top-K retrieval before deterministic reranking; do not automatically choose the top cosine hit.
- Reuse is penalized but not forbidden.
- Same canonical inputs + settings produce deterministic source choices and clip order.
- Historical plan revisions are retained.
- Do not add OTIO, Jianying, captions, transitions, effects, BGM, speed ramps, optical flow, learned reranking, LLM beat rewriting, or final rendering in this subproject.
- Every production behavior is introduced by a failing test first.

---

## File map

Create package:

```text
clipatlas/roughcut/
├── __init__.py      # public exports only
├── contracts.py     # SegmentSearch protocol
├── errors.py        # normalized planning errors
├── models.py        # settings, beat, score, clip, plan
├── beats.py         # narration -> contiguous ScriptBeat windows
├── scoring.py       # lexical features + deterministic candidate score
├── store.py         # SQLite plan revisions / active pointer
└── planner.py       # retrieval, reranking, duration fill, invariant validation
```

API/runtime changes:

```text
clipatlas/app_state.py
clipatlas/api/errors.py
clipatlas/api/routes/rough_cut.py
clipatlas/main.py
README.md
```

Tests:

```text
tests/roughcut/test_models.py
tests/roughcut/test_beats.py
tests/roughcut/test_scoring.py
tests/roughcut/test_store.py
tests/roughcut/test_planner.py
tests/roughcut/test_end_to_end.py
tests/api/test_rough_cut.py
tests/test_roughcut_app_state.py
```

---

### Task 1: Rough-cut domain models, settings, errors, and search protocol

**Files:**
- Create: `clipatlas/roughcut/__init__.py`
- Create: `clipatlas/roughcut/models.py`
- Create: `clipatlas/roughcut/errors.py`
- Create: `clipatlas/roughcut/contracts.py`
- Test: `tests/roughcut/test_models.py`

**Interfaces:**
- Consumes existing `SemanticSearchHit` from `clipatlas.retrieval.search`.
- Produces `PlannerSettings`, `ScriptBeat`, `CandidateScore`, `RoughCutClip`, `RoughCutPlan`.
- Produces `RoughCutError`, `RoughCutConfigurationError`, `RoughCutTimingError`, `RoughCutRetrievalError`, `RoughCutPlanningError`.
- Produces runtime-checkable `SegmentSearch.search(query, limit, video_ids) -> list[SemanticSearchHit]` protocol.

- [ ] **Step 1: Write failing model tests**

Create `tests/roughcut/test_models.py` with at least:

```python
from uuid import uuid4

import pytest
from pydantic import ValidationError

from clipatlas.roughcut.models import (
    CandidateScore,
    PlannerSettings,
    RoughCutClip,
    ScriptBeat,
)


def test_script_beat_duration_must_match_timeline_window() -> None:
    with pytest.raises(ValidationError):
        ScriptBeat(
            project_id=uuid4(),
            narration_track_id=uuid4(),
            sequence=0,
            text="她推开仓库门",
            timeline_start_ms=100,
            timeline_end_ms=1100,
            target_duration_ms=900,
            query_text="她推开仓库门",
        )


def test_rough_cut_clip_requires_equal_source_and_timeline_duration() -> None:
    with pytest.raises(ValidationError):
        RoughCutClip(
            beat_id=uuid4(),
            segment_id=uuid4(),
            video_id=uuid4(),
            source_uri="file:///a.mp4",
            source_in_ms=100,
            source_out_ms=900,
            timeline_in_ms=0,
            timeline_out_ms=1000,
            score=0.8,
            score_breakdown=CandidateScore(
                segment_id=uuid4(),
                semantic_score=0.8,
                action_score=0.0,
                scene_score=0.0,
                emotion_score=0.0,
                duration_fit_score=0.8,
                quality_score=0.5,
                continuity_bonus=0.0,
                reuse_penalty=0.0,
                total_score=0.6,
            ),
            selection_reason="test",
        )


def test_default_settings_lock_v01_weights() -> None:
    settings = PlannerSettings()
    assert settings.top_k == 12
    assert settings.semantic_weight == 0.58
    assert settings.action_weight == 0.08
    assert settings.scene_weight == 0.08
    assert settings.emotion_weight == 0.06
    assert settings.duration_weight == 0.12
    assert settings.quality_weight == 0.05
    assert settings.max_continuity_bonus == 0.03
    assert settings.reuse_penalty_per_use == 0.08
    assert settings.max_reuse_penalty == 0.20
```

Also test nonnegative time fields, `timeline_end_ms > timeline_start_ms`, `source_out_ms > source_in_ms`, and `top_k` range `1..100`.

- [ ] **Step 2: Run RED**

Run:

```bash
pytest tests/roughcut/test_models.py -v
```

Expected: collection/import failure because `clipatlas.roughcut` does not exist.

- [ ] **Step 3: Implement minimal models and errors**

`PlannerSettings` exact fields:

```python
class PlannerSettings(BaseModel):
    top_k: int = Field(default=12, ge=1, le=100)
    semantic_weight: float = 0.58
    action_weight: float = 0.08
    scene_weight: float = 0.08
    emotion_weight: float = 0.06
    duration_weight: float = 0.12
    quality_weight: float = 0.05
    max_continuity_bonus: float = 0.03
    continuity_window_ms: int = Field(default=30_000, gt=0)
    reuse_penalty_per_use: float = 0.08
    max_reuse_penalty: float = 0.20
```

`ScriptBeat` must enforce:

```text
target_duration_ms == timeline_end_ms - timeline_start_ms
```

`RoughCutClip` must enforce:

```text
source_out_ms - source_in_ms == timeline_out_ms - timeline_in_ms
```

`CandidateScore` component values `semantic/action/scene/emotion/duration/quality` are `0..1`, `continuity_bonus >= 0`, `reuse_penalty >= 0`; `total_score` may be negative because penalties are explicit.

`RoughCutPlan` fields:

```python
id: UUID = Field(default_factory=uuid4)
project_id: UUID
narration_track_id: UUID
narration_revision: int = Field(ge=1)
revision: int = Field(ge=1)
total_duration_ms: int = Field(gt=0)
settings: PlannerSettings
beats: list[ScriptBeat]
clips: list[RoughCutClip]
created_at: datetime = Field(default_factory=utc_now)
```

`SegmentSearch` protocol:

```python
@runtime_checkable
class SegmentSearch(Protocol):
    async def search(
        self,
        query: str,
        limit: int = 10,
        video_ids: list[UUID] | None = None,
    ) -> list[SemanticSearchHit]: ...
```

- [ ] **Step 4: Run GREEN/static checks**

Run:

```bash
ruff check clipatlas/roughcut tests/roughcut/test_models.py
mypy clipatlas/roughcut
pytest tests/roughcut/test_models.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add clipatlas/roughcut tests/roughcut/test_models.py
git commit -m "feat: add rough cut domain contracts"
```

---

### Task 2: Build contiguous ScriptBeat windows from the active narration clock

**Files:**
- Create: `clipatlas/roughcut/beats.py`
- Test: `tests/roughcut/test_beats.py`

**Interfaces:**
- Consumes `NarrationTrack`, ordered `list[NarrationUnit]`.
- Produces `BeatBuilder.build(track, units) -> list[ScriptBeat]`.
- Raises `RoughCutTimingError` for unsupported/invalid timing.

- [ ] **Step 1: Write RED tests for exact timing and silence ownership**

Create tests that construct a `UNIT_EXACT` track and assert:

```python
beats = BeatBuilder().build(
    track,
    [
        unit(sequence=0, text="第一句", start_ms=200, end_ms=1000),
        unit(sequence=1, text="第二句", start_ms=1400, end_ms=2200),
    ],
)

assert [(b.timeline_start_ms, b.timeline_end_ms) for b in beats] == [
    (0, 1200),
    (1200, track.duration_ms),
]
assert beats[0].query_text == "第一句"
assert beats[1].query_text == "第二句"
```

The 400 ms internal silence is split at 1200; leading silence goes to beat 0 and trailing silence goes to the last beat.

Also test:

- already contiguous unit timings remain unchanged except leading/trailing ownership;
- `TRACK_ONLY` raises `RoughCutTimingError`;
- `ESTIMATED` raises `RoughCutTimingError`;
- untimed units raise;
- overlapping units raise;
- a unit ending after track duration raises;
- sequence must be deterministic/ordered;
- empty text raises;
- resulting beats start at `0`, end at `track.duration_ms`, and every adjacent pair is contiguous.

- [ ] **Step 2: Run RED**

```bash
pytest tests/roughcut/test_beats.py -v
```

Expected: FAIL because `BeatBuilder` does not exist.

- [ ] **Step 3: Implement BeatBuilder**

Algorithm:

```text
1. reject timing_quality in {TRACK_ONLY, ESTIMATED}
2. sort units by sequence; require at least one
3. validate each unit has non-empty text and exact start/end
4. validate non-overlap and end <= track.duration_ms
5. destination start of first beat = 0
6. for each internal gap:
   boundary = previous.end_ms if contiguous
   otherwise boundary = previous.end_ms + (next.start_ms - previous.end_ms) // 2
7. previous beat ends at boundary; next begins at boundary
8. final beat ends at track.duration_ms
9. query_text = stripped narration unit text
```

Do not fabricate word timing or rewrite semantic text.

- [ ] **Step 4: Run GREEN/static checks**

```bash
ruff check clipatlas/roughcut/beats.py tests/roughcut/test_beats.py
mypy clipatlas/roughcut/beats.py
pytest tests/roughcut/test_beats.py -v
```

- [ ] **Step 5: Commit**

```bash
git add clipatlas/roughcut/beats.py tests/roughcut/test_beats.py
git commit -m "feat: derive rough cut beats from narration timing"
```

---

### Task 3: Deterministic lexical signals and candidate reranking

**Files:**
- Create: `clipatlas/roughcut/scoring.py`
- Test: `tests/roughcut/test_scoring.py`

**Interfaces:**
- Consumes `ScriptBeat`, `SemanticSearchHit`, `PlannerSettings`, prior segment-use count, optional previous `RoughCutClip`.
- Produces `extract_features(text) -> set[str]`, `overlap_score(left, right) -> float`, `CandidateScorer.score(...) -> CandidateScore`.

- [ ] **Step 1: Write RED feature/scoring tests**

Required behavior examples:

```python
assert {"door", "opens", "仓", "库", "仓库"}.issubset(
    extract_features("Door opens 仓库")
)
```

Structured fields must influence rank independently of semantic similarity. Construct two `SemanticSearchHit` objects with identical `score=0.80`; the hit whose annotation `actions=["推门"]` overlaps beat text `"她推门进入仓库"` must receive higher `total_score` than one with unrelated actions.

Also test:

- cosine values below 0 clamp to semantic score 0; above 1 clamp to 1;
- exact duration match gives `duration_fit_score == 1.0`;
- 500 ms candidate for a 1000 ms need gives `0.5`;
- annotation confidence is used as quality base; `verified=True` adds a small fixed bonus but remains <=1;
- same-video nearby non-overlapping previous clip receives a continuity bonus <=0.03;
- overlapping same-source ranges do not receive continuity bonus;
- prior use count 1 gives 0.08 reuse penalty, 3+ uses cap at 0.20;
- equal scores remain exactly equal here; deterministic tie-breaking belongs to planner selection.

- [ ] **Step 2: Run RED**

```bash
pytest tests/roughcut/test_scoring.py -v
```

Expected: FAIL because scoring module does not exist.

- [ ] **Step 3: Implement minimal deterministic scorer**

Feature extraction:

```text
- lowercase Latin/digit runs `[a-z0-9]+`
- each CJK character `\u4e00-\u9fff`
- overlapping two-character CJK grams from contiguous CJK runs
```

`overlap_score` uses overlap coefficient:

```python
len(left & right) / min(len(left), len(right))
```

and returns `0.0` when either set is empty.

Compute structured features independently from:

```python
annotation.actions
annotation.scene
annotation.emotions
```

Default quality rule:

```python
quality = annotation.confidence if annotation.confidence is not None else 0.5
if annotation.verified:
    quality = min(1.0, quality + 0.10)
```

Continuity rule: same video, no source overlap, nearest endpoint distance <= `continuity_window_ms`; linear bonus from `max_continuity_bonus` down to 0 as distance approaches the window.

Total uses the exact weights from the spec/settings.

- [ ] **Step 4: Run GREEN/static checks**

```bash
ruff check clipatlas/roughcut/scoring.py tests/roughcut/test_scoring.py
mypy clipatlas/roughcut/scoring.py
pytest tests/roughcut/test_scoring.py -v
```

- [ ] **Step 5: Commit**

```bash
git add clipatlas/roughcut/scoring.py tests/roughcut/test_scoring.py
git commit -m "feat: add deterministic rough cut reranking"
```

---

### Task 4: Persist rough-cut plan revisions and active pointer

**Files:**
- Create: `clipatlas/roughcut/store.py`
- Test: `tests/roughcut/test_store.py`

**Interfaces:**
- Produces `RoughCutStore(db_path: Path)`.
- Methods:
  - `save_plan(plan: RoughCutPlan) -> None`
  - `get_plan(plan_id: UUID) -> RoughCutPlan | None`
  - `next_plan_revision(project_id: UUID) -> int`
  - `activate_plan(project_id: UUID, plan_id: UUID) -> bool`
  - `get_active_plan(project_id: UUID) -> RoughCutPlan | None`

- [ ] **Step 1: Write RED persistence/history tests**

Test:

- a saved plan survives store reopen;
- revision 1 and revision 2 both remain retrievable;
- `next_plan_revision()` increments per project;
- activation only succeeds when the plan belongs to the project;
- changing active plan does not delete the old plan;
- a different project's revisions/active pointer are isolated.

- [ ] **Step 2: Run RED**

```bash
pytest tests/roughcut/test_store.py -v
```

Expected: FAIL because store does not exist.

- [ ] **Step 3: Implement SQLite store**

Schema:

```sql
CREATE TABLE IF NOT EXISTS rough_cut_plans (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rough_cut_plans_project_revision
ON rough_cut_plans(project_id, revision DESC, created_at DESC);

CREATE TABLE IF NOT EXISTS active_rough_cut_plans (
    project_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    FOREIGN KEY(plan_id) REFERENCES rough_cut_plans(id)
);
```

Use the same path canonicalization/connection conventions as `NarrationStore`. Normal operations never delete historical plans.

- [ ] **Step 4: Run GREEN/static checks**

```bash
ruff check clipatlas/roughcut/store.py tests/roughcut/test_store.py
mypy clipatlas/roughcut/store.py
pytest tests/roughcut/test_store.py -v
```

- [ ] **Step 5: Commit**

```bash
git add clipatlas/roughcut/store.py tests/roughcut/test_store.py
git commit -m "feat: persist rough cut plan revisions"
```

---

### Task 5: RoughCutPlanner retrieval, deterministic selection, and duration filling

**Files:**
- Create: `clipatlas/roughcut/planner.py`
- Test: `tests/roughcut/test_planner.py`

**Interfaces:**
- Consumes `NarrationStore`, `SegmentSearch`, `RoughCutStore`, `BeatBuilder`, `CandidateScorer`, `PlannerSettings`.
- Produces `RoughCutPlanner.create_plan(project_id, top_k=None, video_ids=None) -> RoughCutPlan`.

- [ ] **Step 1: Write RED planner tests with a deterministic in-memory search fake**

The fake search must record calls and return real `SemanticSearchHit` model instances. Do not mock `RoughCutPlanner` internals.

Required tests:

1. **Top-K is called for every beat.** Two narration units -> exactly two search calls with `limit=12` by default.
2. **One long source segment fills a beat.** A 5000 ms source segment filling a 1200 ms beat yields `source_out_ms - source_in_ms == 1200` and remains inside canonical bounds.
3. **Several short segments fill one beat.** 400 + 500 + 300 ms selected ranges cover a 1200 ms beat with no destination gaps.
4. **Source bounds are hard.** No output clip starts before hit start or ends after hit end.
5. **Reuse penalty changes later selection.** Two initially similar candidates should cause the previously unused segment to win on the next beat when its total score becomes higher after reuse penalty.
6. **Deterministic ties.** Equal total/semantic/use count picks lexical `segment_id` order.
7. **Missing active narration raises `RoughCutConfigurationError`.**
8. **TRACK_ONLY active narration propagates timing rejection.**
9. **No retrieval hits raises `RoughCutRetrievalError`.**
10. **Final timeline covers exactly `0..track.duration_ms`.**
11. **Plan is persisted and activated only after validation succeeds.**
12. **`video_ids` filter is passed unchanged to every search call.**

- [ ] **Step 2: Run RED**

```bash
pytest tests/roughcut/test_planner.py -v
```

Expected: FAIL because planner does not exist.

- [ ] **Step 3: Implement selection and filling**

Constructor:

```python
class RoughCutPlanner:
    def __init__(
        self,
        *,
        narration_store: NarrationStore,
        search: SegmentSearch,
        store: RoughCutStore,
        settings: PlannerSettings | None = None,
        beat_builder: BeatBuilder | None = None,
        scorer: CandidateScorer | None = None,
    ) -> None: ...
```

Primary method:

```python
async def create_plan(
    self,
    project_id: UUID,
    *,
    top_k: int | None = None,
    video_ids: list[UUID] | None = None,
) -> RoughCutPlan:
    ...
```

Selection loop per beat:

```text
hits = await search.search(beat.query_text, limit=resolved_top_k, video_ids=video_ids)
remaining = beat.target_duration_ms
cursor = beat.timeline_start_ms
while remaining > 0:
    score each hit using current reuse_counts and previous_clip
    rank by (-total_score, -semantic_score, prior_use_count, str(segment_id))
    prefer candidates not yet used inside the current beat
    if every candidate has been used inside the current beat, allow another pass with reuse penalty
    selected_source_in = hit.source_start_ms
    selected_duration = min(remaining, hit.source_end_ms - hit.source_start_ms)
    selected_source_out = selected_source_in + selected_duration
    append clip at timeline cursor
    increment reuse count
    cursor += selected_duration
    remaining -= selected_duration
```

Important guard: a zero/negative-duration hit is invalid and must never produce a clip. If all hits are unusable, raise `RoughCutRetrievalError`.

After all beats:

Validate:

```text
clips are ordered by timeline_in
first timeline_in == 0
last timeline_out == track.duration_ms
adjacent timeline_out == next.timeline_in
source range is inside the corresponding search hit canonical bounds
clip source duration == timeline duration
```

Only then build/save/activate the plan.

Selection reason must be deterministic text generated from score components, for example:

```text
semantic=0.820; action=0.500; scene=0.000; emotion=0.000; duration=1.000; quality=0.700; continuity=0.020; reuse=0.080; total=0.603
```

Do not use free-form AI text as the reason.

- [ ] **Step 4: Run GREEN/static checks**

```bash
ruff check clipatlas/roughcut/planner.py tests/roughcut/test_planner.py
mypy clipatlas/roughcut/planner.py
pytest tests/roughcut/test_planner.py -v
```

Then run all rough-cut tests so far:

```bash
pytest tests/roughcut -v
```

- [ ] **Step 5: Commit**

```bash
git add clipatlas/roughcut/planner.py tests/roughcut/test_planner.py
git commit -m "feat: generate deterministic rough cut plans"
```

---

### Task 6: Runtime construction without coupling planner to FastAPI or Jianying

**Files:**
- Modify: `clipatlas/app_state.py`
- Modify: `.env.example`
- Test: `tests/test_roughcut_app_state.py`

**Interfaces:**
- Produces `RoughCutRuntime(store: RoughCutStore, planner: RoughCutPlanner | None)`.
- Produces `build_rough_cut_runtime(narration_store, semantic_search_service) -> RoughCutRuntime`.
- Environment: `CLIPATLAS_ROUGHCUT_DB`, default `./data/roughcut/roughcut.sqlite3`.

- [ ] **Step 1: Write RED runtime tests**

Required tests:

- with a semantic search service, runtime contains a planner and store;
- with `semantic_search_service=None`, runtime store still exists but planner is `None`;
- `CLIPATLAS_ROUGHCUT_DB` controls persistence location;
- runtime reuses the supplied `NarrationStore` instead of creating a second narration DB.

- [ ] **Step 2: Run RED**

```bash
pytest tests/test_roughcut_app_state.py -v
```

Expected: FAIL because rough-cut runtime does not exist.

- [ ] **Step 3: Implement runtime wiring**

Add imports and dataclass:

```python
@dataclass(frozen=True, slots=True)
class RoughCutRuntime:
    store: RoughCutStore
    planner: RoughCutPlanner | None
```

Builder:

```python
def build_rough_cut_runtime(
    narration_store: NarrationStore,
    semantic_search_service: SemanticSearchService | None,
) -> RoughCutRuntime:
    store = RoughCutStore(
        Path(os.getenv("CLIPATLAS_ROUGHCUT_DB", "./data/roughcut/roughcut.sqlite3"))
    )
    planner = None
    if semantic_search_service is not None:
        planner = RoughCutPlanner(
            narration_store=narration_store,
            search=semantic_search_service,
            store=store,
        )
    return RoughCutRuntime(store=store, planner=planner)
```

Add `.env.example`:

```text
CLIPATLAS_ROUGHCUT_DB=./data/roughcut/roughcut.sqlite3
```

No OTIO/Jianying imports.

- [ ] **Step 4: Run GREEN/static checks**

```bash
ruff check clipatlas/app_state.py tests/test_roughcut_app_state.py
mypy clipatlas/app_state.py
pytest tests/test_roughcut_app_state.py -v
```

- [ ] **Step 5: Commit**

```bash
git add clipatlas/app_state.py .env.example tests/test_roughcut_app_state.py
git commit -m "feat: wire rough cut runtime"
```

---

### Task 7: Rough-cut API and normalized errors

**Files:**
- Create: `clipatlas/api/routes/rough_cut.py`
- Modify: `clipatlas/api/errors.py`
- Modify: `clipatlas/main.py`
- Test: `tests/api/test_rough_cut.py`

**Interfaces:**
- `POST /api/v1/rough-cut/plans`
- `GET /api/v1/rough-cut/plans/active?project_id=<uuid>`
- `GET /api/v1/rough-cut/plans/{plan_id}`

- [ ] **Step 1: Write RED API tests**

Build a small FastAPI test app with a real `RoughCutStore` and a stub planner that returns a real `RoughCutPlan`.

Required cases:

- create endpoint passes `project_id`, `top_k`, and optional `video_ids` to planner;
- default `top_k` is 12;
- request validation rejects `top_k=0` and `top_k=101` with 422;
- create returns 503 with stable code `rough_cut_unavailable` when `app.state.rough_cut_planner is None`;
- missing active plan returns 404 `rough_cut_plan_not_found`;
- fetching an unknown plan ID returns 404;
- timing/configuration planning error maps to 409 `rough_cut_not_ready`;
- retrieval runtime/error maps to 503 `rough_cut_retrieval_failed`.

- [ ] **Step 2: Run RED**

```bash
pytest tests/api/test_rough_cut.py -v
```

Expected: FAIL because the route/error handlers do not exist.

- [ ] **Step 3: Implement API and handlers**

Request model:

```python
class CreateRoughCutPlanRequest(BaseModel):
    project_id: UUID
    top_k: int = Field(default=12, ge=1, le=100)
    video_ids: list[UUID] | None = None
```

Create endpoint:

```python
planner = request.app.state.rough_cut_planner
if planner is None:
    raise RoughCutRetrievalError("Semantic retrieval is not configured")
return await planner.create_plan(
    payload.project_id,
    top_k=payload.top_k,
    video_ids=payload.video_ids,
)
```

For lookups, use `request.app.state.rough_cut_store`.

Extend `register_error_handlers()` with stable normalized JSON:

```text
RoughCutConfigurationError / RoughCutTimingError -> 409 rough_cut_not_ready
RoughCutRetrievalError -> 503 rough_cut_retrieval_failed
RoughCutPlanningError -> 500 rough_cut_planning_failed
```

For missing plan, route-level `HTTPException(status_code=404, detail=...)` is acceptable only if existing API style already uses it; otherwise return the project's normalized error shape. Keep tests aligned with the chosen existing style.

Modify `create_app()`:

```text
semantic_search_service = existing app.state.semantic_search_service
narration_store = existing app.state.narration_store
roughcut_runtime = build_rough_cut_runtime(narration_store, semantic_search_service)
app.state.rough_cut_store = roughcut_runtime.store
app.state.rough_cut_planner = roughcut_runtime.planner
include rough_cut_router
```

- [ ] **Step 4: Run GREEN/static checks**

```bash
ruff check clipatlas/api/routes/rough_cut.py clipatlas/api/errors.py clipatlas/main.py tests/api/test_rough_cut.py
mypy clipatlas/api/routes/rough_cut.py clipatlas/api/errors.py clipatlas/main.py
pytest tests/api/test_rough_cut.py -v
```

- [ ] **Step 5: Commit**

```bash
git add clipatlas/api/routes/rough_cut.py clipatlas/api/errors.py clipatlas/main.py tests/api/test_rough_cut.py
git commit -m "feat: expose rough cut planning API"
```

---

### Task 8: End-to-end invariant test, documentation, and full verification

**Files:**
- Create: `tests/roughcut/test_end_to_end.py`
- Modify: `README.md`
- Create: `docs/script-to-rough-cut-v0.1.md`

**Interfaces:**
- Proves the A+B+C handoff without OTIO/Jianying.

- [ ] **Step 1: Write the end-to-end invariant test**

Use real:

- `NarrationStore`
- `NarrationTrack`/`NarrationUnit`
- `RoughCutStore`
- `RoughCutPlanner`
- `SemanticSearchHit`

Use only a deterministic in-memory `SegmentSearch` fake to avoid calling a live embedding API.

Scenario:

```text
NarrationTrack duration 3500 ms
Unit 0: 0..1200 "女人推开旧仓库门"
Unit 1: 1200..2000 "她看到桌上的红色文件夹"
Unit 2: 2000..3500 "远处警灯照亮雨夜街道"
```

Provide semantically distinct footage candidates with exact source bounds. Assert:

```python
assert plan.total_duration_ms == 3500
assert plan.clips[0].timeline_in_ms == 0
assert plan.clips[-1].timeline_out_ms == 3500
assert all(a.timeline_out_ms == b.timeline_in_ms for a, b in pairwise(plan.clips))
assert all(
    clip.source_out_ms - clip.source_in_ms
    == clip.timeline_out_ms - clip.timeline_in_ms
    for clip in plan.clips
)
assert store.get_active_plan(project_id) == plan
```

Also assert each search query equals the corresponding narration-unit text. This proves the planner uses the narration-owned script, not an independently supplied stale copy.

- [ ] **Step 2: Run RED if the invariant exposes any missing behavior**

```bash
pytest tests/roughcut/test_end_to_end.py -v
```

If it passes immediately because Tasks 1-7 already satisfy the behavior, that is acceptable only for this integration test; do not add production behavior in this task unless a new failing requirement is identified.

- [ ] **Step 3: Add Chinese-first documentation**

`README.md` must add a concise current flow:

```text
素材库/语义索引
→ 当前激活旁白（真实时长）
→ ScriptBeat
→ Top-K 语义检索
→ 结构化重排
→ 时长填充
→ RoughCutPlan
→ （下一阶段）OTIO
→ （下一阶段）剪映草稿
```

`docs/script-to-rough-cut-v0.1.md` must document:

- why narration timing is authoritative;
- supported timing qualities;
- Top-K + reranking behavior;
- reuse/continuity policy;
- exact source-boundary rule;
- API examples;
- failure/resume behavior;
- explicit statement that OTIO/Jianying are next stage, not part of V0.1.

- [ ] **Step 4: Run complete fresh verification**

Run exactly:

```bash
ruff check .
mypy clipatlas
pytest -q
```

All three must exit 0. Do not infer full success from partial tests.

- [ ] **Step 5: Verify requirement checklist manually**

Confirm against the design spec:

```text
[ ] active narration is the only automatic beat clock
[ ] TRACK_ONLY/ESTIMATED are rejected
[ ] beat coverage is contiguous and total
[ ] every beat performs Top-K retrieval
[ ] structured/duration/quality/continuity/reuse scoring is active
[ ] reuse is penalized, not forbidden
[ ] long source can trim inside canonical segment
[ ] multiple short sources can fill one beat
[ ] no source clip exceeds canonical bounds
[ ] destination timeline exactly matches narration duration
[ ] deterministic ties are tested
[ ] historical plan revisions persist
[ ] API create/get-active/get-by-id work
[ ] no OTIO/Jianying dependency leaked into roughcut package
```

- [ ] **Step 6: Commit docs/integration test**

```bash
git add tests/roughcut/test_end_to_end.py README.md docs/script-to-rough-cut-v0.1.md
git commit -m "docs: finalize script to rough cut v0.1"
```

- [ ] **Step 7: Open/refresh non-draft PR and require fresh CI**

The PR must target `main` from `feat/script-to-rough-cut-v0.1` and must not be Draft because the current GitHub connector has a known ready-for-review GraphQL compatibility problem.

Before merge, fresh CI on the exact head SHA must show:

```text
Install: success
Ruff: success
Mypy: success
Pytest: success
```

Only merge after that exact evidence exists.

---

## Self-review against spec

- Beat timing authority and silence ownership: Task 2.
- Top-K retrieval contract: Tasks 1 and 5.
- Multi-signal deterministic reranking: Task 3.
- Duration filling, hard source bounds, reuse and deterministic tie-breaks: Task 5.
- Independent plan persistence/history: Task 4.
- Runtime isolation: Task 6.
- API and normalized failures: Task 7.
- A+B+C integration and no stale duplicate script: Task 8.
- OTIO/Jianying explicitly excluded: Global Constraints and Task 8 checklist.

No placeholder tasks remain; every production component is introduced after a RED test except documentation/config-only edits.
# FineCut Independent Module V0.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build FineCut as an independently testable source module and connect it to ClipAtlas through a narrow Bridge without changing the stable AI/retrieval/RoughCut core.

**Architecture:** `modules/finecut` owns only editing-domain state, timeline persistence, effects/external-resource/rendering added phase-by-phase. `clipatlas/integrations/finecut` converts existing ClipAtlas data into FineCut public models. Dependency direction is one-way: ClipAtlas Bridge -> FineCut; FineCut never imports ClipAtlas.

**Tech Stack:** Python 3.12, Pydantic 2, SQLite, FastAPI integration at ClipAtlas boundary, React/TypeScript for UI in later phases, existing ClipAtlas subprocess/FFmpeg infrastructure where integration requires it.

**Spec:** `docs/superpowers/specs/2026-09-14-finecut-independent-module-design.md`

## Global Constraints

- Work only on `feat/intelligent-finecut-external-workspace-v0.1`.
- Do not modify `main` or `visual-timeline-global-match-v1`.
- Do not open a PR.
- Do not refactor `roughcut`, `director`, `retrieval`, candidate matrix, global assignment, word timing, pollution gate, cooldown, narration, or TTS.
- FineCut must not import ClipAtlas packages.
- No second material library, vector index, Candidate Matrix, RoughCut, or narration/word-timing pipeline.
- No new AI/API calls for editing or candidate display.
- No PluginHost, SceneGraph, NodeGraph, RenderScheduler, GraphEngine, AnimationGraph, plugin market, or second EventBus.
- Before every implementation task, answer the five module gates: necessary now; simpler existing option; inside current phase; no overthinking; no future feature prebuild.
- TDD: failing test first, minimal implementation second.

---

### Task 1: Independent FineCut package + TimelineDocument

**Files:**
- Create: `modules/finecut/pyproject.toml`
- Create: `modules/finecut/finecut/__init__.py`
- Create: `modules/finecut/finecut/models.py`
- Create: `modules/finecut/tests/test_models.py`

**Interfaces:**
- Produces: `finecut.models.TimelineDocument`, `Track`, `Clip`.
- Consumes: only Python/Pydantic; no `clipatlas.*` imports.

- [ ] Gate review: prove an independent package is necessary for source isolation; keep models in one file until size/usage justifies splitting.
- [ ] Write failing tests for model validation: track kinds, positive dimensions/fps, source/timeline windows, and document duration.
- [ ] Run only `modules/finecut/tests/test_models.py` and verify RED.
- [ ] Add minimal package metadata and Pydantic models with only fields approved in the spec.
- [ ] Run test and verify GREEN.
- [ ] Run a static import check proving `finecut` has no `clipatlas` dependency.
- [ ] Commit only Task 1 files.

### Task 2: RoughCut -> Timeline Bridge

**Files:**
- Create: `clipatlas/integrations/finecut/__init__.py`
- Create: `clipatlas/integrations/finecut/roughcut_bridge.py`
- Create: `tests/integrations/finecut/test_roughcut_bridge.py`

**Interfaces:**
- Consumes: `clipatlas.roughcut.models.RoughCutPlan`; produces `finecut.models.TimelineDocument`.
- Public function: `timeline_from_roughcut(plan: RoughCutPlan, *, width: int = 1920, height: int = 1080, fps: float = 30.0) -> TimelineDocument`.

- [ ] Gate review: use one plain function, not an adapter class/service/manager.
- [ ] Write RED tests proving exact equality of `source_in_ms`, `source_out_ms`, and timeline start/duration from RoughCut clips.
- [ ] Test that subtitles and narration timing are not regenerated or mutated.
- [ ] Implement minimal mapping with one V1 video track; create only tracks justified by current RoughCut data.
- [ ] Run bridge tests GREEN.
- [ ] Run existing roughcut tests most directly touching models/store to ensure no regression.
- [ ] Commit only bridge/test changes.

### Task 3: FineCut TimelineStore

**Files:**
- Create: `modules/finecut/finecut/store.py`
- Create: `modules/finecut/tests/test_store.py`

**Interfaces:**
- Consumes/produces `TimelineDocument` JSON.
- Public methods limited to current need: `save(document)`, `get(project_id, source_plan_id)`, and `delete(...)` only if a current caller exists.

- [ ] Gate review: SQLite is only for final `TimelineDocument` restart recovery; keep exactly one timeline table and do not persist Undo/Redo command history, Candidate Matrix, S/A/B, material copies, or separate Workspace state.
- [ ] Write RED test for save/reload preserving the exact document.
- [ ] Implement one SQLite table with JSON payload and minimal keys.
- [ ] Verify restart persistence test GREEN.
- [ ] Confirm schema stores no Candidate Matrix/vector/material copies.
- [ ] Commit.

### Task 4: Candidate Bridge read model

**Files:**
- Create: `modules/finecut/finecut/candidates.py` only if a dedicated public model is needed; otherwise keep DTO in `models.py`.
- Create: `clipatlas/integrations/finecut/candidate_bridge.py`
- Create: `tests/integrations/finecut/test_candidate_bridge.py`

**Interfaces:**
- Public function returns `CandidateList` for a given beat/context from Candidate Matrix data already present in the persisted RoughCut plan.

- [ ] Gate review: do not copy Candidate Matrix into FineCut persistence; use one plain projection function.
- [ ] Write RED tests for `DIRECT->S`, `SUPPORT->A`, `RELATED->B`, `GENERIC->Generic`, SOURCE/REUSE fallback preservation, UNKNOWN hiding, REJECT/blocked/illegal filtering, original order, independent `importance`, and passthrough of existing source/anchor/continuity/family/presentation/score fields.
- [ ] Do not add AI reason, explanation, recommendation score, thumbnail DTO, reranking, rescoring, retrieval, Director, or API calls.
- [ ] Implement read-only projection.
- [ ] Verify existing planner/candidate-matrix tests most directly affected still pass.
- [ ] Commit.

### Task 5: Read-only Intelligent FineCut workspace

**Files:**
- Create only the minimum FineCut UI files under `modules/finecut/ui/`.
- Modify ClipAtlas main frontend only for FineCut availability, the “智能精剪” entry, and mount/route integration.

**Interfaces:**
- Consumes the frozen `TimelineDocument`, `CandidateList`, `NarrationReference`, and `MediaReference` contracts.
- FineCut internal Timeline/Candidate/Inspector components remain under `modules/finecut/ui/`; they must not be scattered into `frontend/src/features/`.

- [ ] Gate review: read-only only; no drag, trim, split, delete, replace, undo, redo, effects, or external workspace.
- [ ] Write focused UI RED tests proving selecting narration context A renders CandidateList A, switching to B immediately renders CandidateList B, SOURCE/REUSE appear only in the collapsed fallback section, and UNKNOWN/REJECT/blocked/illegal are not rendered.
- [ ] Render the initial “智能精剪” layout with candidate panel, preview area, V1 timeline, T1 narration text/subtitle context, and A1 narration lane.
- [ ] Candidate cards may render only fields already present in the frozen Candidate contract; do not invent AI reason/explanation/recommendation score/thumbnail DTO.
- [ ] Reuse an existing thumbnail/media path only if it is already available by `media_id`; otherwise use a placeholder in Phase 2.
- [ ] Support loading the TimelineDocument, showing clips and narration segments, selecting/highlighting current segment/clip, and seek; add play/pause only if existing preview capability is directly reusable without new media infrastructure.
- [ ] FineCut present -> entry/mount available; FineCut absent -> ClipAtlas remains functional and entry is hidden or unavailable. Do not add plugin discovery/registry/manifest/lifecycle systems.
- [ ] Run FineCut UI focused tests, main frontend typecheck, and the current 18 Python targeted tests.
- [ ] Stop after Phase 2 and report; do not start editing/effects/external workspace.

### Task 6: Editing commands and Undo/Redo

**Files:**
- Add focused files under `modules/finecut/finecut/editing/` only as commands become necessary.
- Add tests under `modules/finecut/tests/editing/`.

**Interfaces:**
- Operations: replace, trim, split, delete, undo, redo.

- [ ] Gate review per operation; no move/keyframe/effect command unless explicitly required by this phase.
- [ ] For each operation: RED test -> minimal implementation -> GREEN before the next operation.
- [ ] Undo/Redo must operate on the same TimelineDocument state and remain in current-session memory; do not persist command history.
- [ ] Persist only the edited final TimelineDocument and verify restart recovery.
- [ ] Commit phase as independently testable unit.

### Task 7: Workspace switch

**Files:**
- Modify FineCut UI workspace/layout state only.

- [ ] Gate review: switching workspaces is presentation state, not a second editor.
- [ ] RED test that both workspaces reference the same document identity/content and preserve playhead/history.
- [ ] Add `智能精剪 <-> 外部工程` layout switch.
- [ ] Verify timeline, playhead, effects, and history remain unchanged.
- [ ] Commit.

### Task 8: External resource read-only scan/catalog

**Files:**
- Add only the minimum files under `modules/finecut/finecut/external/`.
- Add synthetic fixtures/tests; never commit real third-party packages.
- Modify `.gitignore` only when private fixture paths are actually introduced.

- [ ] Gate review: scan only user-selected/confirmed paths; no full-disk scanner, runtime VM, decryption, authentication bypass, or script execution.
- [ ] RED tests for classify/status mapping using synthetic JSON/text fixtures.
- [ ] Implement scanner/catalog/read-only importer with no execution of JS/Lua.
- [ ] Add optional real-world test gated by `CLIPATLAS_EXTERNAL_EFFECT_FIXTURE_ROOT`.
- [ ] Verify unset env skips real fixture test.
- [ ] Commit.

### Task 9: Minimal effects

**Files:**
- Add effect definitions/renderer implementation only for `text_pop`, `crossfade`, `spatial_rotate` plus already-approved minimal basics when needed by tests.

- [ ] Gate review before each effect; no generic plugin framework or keyframe engine.
- [ ] RED tests for effect parameter serialization and render-plan projection.
- [ ] Implement `text_pop` and `crossfade` minimally.
- [ ] Implement `spatial_rotate` with ClipAtlas/FineCut-owned shader logic, not copied third-party shader source.
- [ ] Verify all three effects survive save/reload and workspace switch.
- [ ] Commit.

### Task 10: Native local MP4 export

**Files:**
- Add the minimum render-plan/export files under `modules/finecut/finecut/render/`.
- Reuse existing safe ClipAtlas FFmpeg process boundary through integration rather than reimplementing shell execution in FineCut if practical without reversing dependency direction.

- [ ] Gate review: no Remotion, AE runtime, external editor renderer, render scheduler, or `shell=True`.
- [ ] Write RED integration tests for trim, subtitle/text, narration/audio, candidate replacement, crossfade, spatial_rotate entering the render plan.
- [ ] Implement minimal render plan and local export path.
- [ ] Run a real 10-30 second MP4 black-box export.
- [ ] Verify resulting file with ffprobe and relevant visual/timing checks.
- [ ] Commit.

### Task 11: Final V0.1 hard gate

- [ ] Run FineCut Python tests.
- [ ] Run affected ClipAtlas roughcut/export/API tests.
- [ ] Run FineCut/frontend targeted Vitest tests.
- [ ] Verify no `finecut` source imports `clipatlas`.
- [ ] Search repository for forbidden third-party fixture paths/secrets/cache artifacts.
- [ ] Compare branch against locked baseline and produce `git diff --stat` equivalent from GitHub compare if local CLI is unavailable.
- [ ] Answer every required phase self-check item.
- [ ] Stop feature expansion and enter real fine-cut black-box testing.

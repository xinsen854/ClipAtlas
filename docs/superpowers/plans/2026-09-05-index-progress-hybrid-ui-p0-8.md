# Index Progress + Hybrid Recall UI P0-8 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or subagent-driven development. Execute with TDD and reverse-audit after each task.

**Goal:** Show existing Visual/ASR/OCR index progress and Hybrid recall provenance without adding new persistence or runtime processing.

**Architecture:** Add one read-only SQLite progress reader, expose one video progress endpoint, then connect existing frontend material/search pages to that endpoint and `/search/hybrid`.

**Spec:** `docs/superpowers/specs/2026-09-05-index-progress-hybrid-ui-design.md`

## Constraints

- No new DB tables or writes.
- No polling/WebSocket/SSE.
- No new retrieval or indexing logic.
- No duplicate Bailian model UI.
- No DeepPass public UI/API.

### Task 1: Read-only index progress

**Files:**
- Create: `clipatlas/library/index_progress.py`
- Test: `tests/library/test_index_progress.py`

- [ ] RED tests for visual counts, latest ASR/OCR revision, disabled source, no-audio ASR.
- [ ] Implement `IndexSourceProgress`, `VideoIndexProgress`, `LibraryIndexProgressReader` using SELECT-only queries.
- [ ] Keep all progress persistence out of this reader; it must create no tables and write no state.
- [ ] GREEN targeted tests when executable.

### Task 2: Progress API and runtime wiring

**Files:**
- Modify: `clipatlas/main.py`
- Modify: `clipatlas/api/routes/videos.py`
- Test: `tests/api/test_video_index_progress.py`

- [ ] RED API test for progress response and existing video 404.
- [ ] Attach `LibraryIndexProgressReader` directly in `main.py` from the existing library DB path/current runtime configuration; do not expand `LibraryRuntime` or modify `app_state.py` for UI-only state.
- [ ] Add `GET /api/v1/videos/{video_id}/index-progress`.
- [ ] GREEN targeted tests when executable.

### Task 3: Hybrid search UI

**Files:**
- Modify: `frontend/src/api/search.ts`
- Modify: `frontend/src/features/search/SearchPage.tsx`
- Modify: `frontend/src/features/search/SearchPage.test.tsx`

- [ ] RED tests for default Hybrid mode and visual/ASR/OCR provenance rendering.
- [ ] Add `HybridSearchHit` + `searchHybrid()` and minimal result card.
- [ ] Preserve 5s/30s/legacy semantic modes.
- [ ] GREEN targeted frontend tests when executable.

### Task 4: Material progress UI + reverse audit

**Files:**
- Modify: `frontend/src/api/library.ts`
- Modify: `frontend/src/features/library/LibraryItemPage.tsx`
- Add focused test only if existing LibraryItemPage testing pattern supports it without large fixture duplication.

- [ ] Add progress API type/client.
- [ ] Render Visual/ASR/OCR rows with disabled/not-applicable/completed states.
- [ ] Compare P0-8 head to P0-7 base and confirm only progress read/API and two existing UI surfaces changed.
- [ ] Remove formatting-only churn before final review.
- [ ] Run available targeted verification; record zero-step CI honestly.

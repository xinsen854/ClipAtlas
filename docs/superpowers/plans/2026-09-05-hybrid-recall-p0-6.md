# Hybrid Recall P0-6 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add explainable hybrid recall that combines the existing 5-second visual search with completed ASR sentences and OCR text, then merges overlapping/adjacent evidence into de-duplicated timeline candidates.

**Architecture:** Keep ASR and OCR persistence independent. Add narrow read/search methods to the existing stores, then use one in-memory `HybridSearchService` to combine visual/ASR/OCR evidence. Visual recall is optional: existing ASR/OCR evidence remains searchable when visual search is unavailable. No fused-result persistence is added.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic, sqlite3, existing ClipAtlas `CoarseVideoSearchService`, `ASRStore`, `OCRStore`.

**Spec:** `docs/superpowers/specs/2026-09-05-qwen-unified-ai-stack-design.md`

## Global Constraints

- Exactly three P0-6 recall sources: visual, ASR, OCR.
- No learned reranker, `qwen3-vl-rerank`, FTS table, ASR/OCR embedding index, new database, queue, checkpoint system, or fused-result table.
- Existing `/search/segments` and `/search/video-chunks` behavior remains unchanged.
- TTS, OTIO, Jianying, Human > AI revisions, deep understanding, and rough-cut behavior remain unchanged.
- Formal ASR/OCR IDs remain `bailian-asr` / `qwen-audio-3.0-asr-flash` and `bailian-ocr` / `qwen3.5-ocr`.
- Temporal merge gap is `DEFAULT_VIDEO_INDEX_PROFILE.overlap_ms` (`1000ms`).
- Duplicate evidence from one source contributes only that source's maximum score to a merged candidate.

---

### Task 1: Latest-success ASR keyword recall

**Files:**
- Modify: `clipatlas/asr/models.py`
- Modify: `clipatlas/asr/store.py`
- Test: `tests/asr/test_hybrid_recall.py`

**Interfaces:**
- `ASRTextMatch(video_id, start_ms, end_ms, text, revision)`
- `ASRStore.search_text(query, provider, model, *, limit, video_ids=None)`

- [x] Add RED tests for completed latest-success recall, failed-revision fallback, filtering, blank query, and limit.
- [x] Implement a read-only latest-completed revision query over the existing table.
- [x] Verify focused tests: 3 passed.

### Task 2: Latest-success OCR keyword recall

**Files:**
- Modify: `clipatlas/ocr/models.py`
- Modify: `clipatlas/ocr/store.py`
- Test: `tests/ocr/test_hybrid_recall.py`

**Interfaces:**
- `OCRTextMatch(video_id, start_ms, end_ms, text, revision, interval_ms)`
- `OCRStore.search_text(query, provider, model, *, limit, video_ids=None)`

- [x] Add RED tests for latest-success recall, failed-revision fallback, blank OCR, filtering, blank query, and limit.
- [x] Implement a read-only latest-completed revision query over the existing table.
- [x] Verify focused tests: 3 passed.

### Task 3: Hybrid candidate merge and explainable score fusion

**Files:**
- Create: `clipatlas/retrieval/hybrid.py`
- Test: `tests/retrieval/test_hybrid_search.py`

**Behavior:**
- Text specificity: `len(normalized_query) / len(normalized_text)` for substring matches, capped at `1.0`.
- Visual contribution: cosine score clamped to `[0,1]`.
- Per merged span, keep only max contribution from each source.
- Final score is the sum of present source contributions.
- Merge same-video evidence when `next.start_ms <= current.end_ms + 1000`.
- Preserve `visual_score`, `asr_score`, `ocr_score`, source list, and ASR/OCR provenance text.

- [x] Add RED tests for three-source merge, adjacency boundary, duplicate visual evidence, text-only mode, filtering, and deterministic ordering.
- [x] Implement in-memory fusion only.
- [x] Verify representative focused tests: 3 passed.

### Task 4: Runtime and API exposure

**Files:**
- Modify: `clipatlas/retrieval/hybrid.py`
- Modify: `clipatlas/main.py`
- Modify: `clipatlas/api/routes/search.py`
- Test: `tests/retrieval/test_hybrid_runtime.py`
- Test: `tests/api/test_hybrid_search.py`

**Interfaces:**
- `build_hybrid_search_service(*, catalog, visual_service, db_path) -> HybridSearchService`
- `GET /api/v1/search/hybrid?q=...&limit=...&video_ids=...`

**Minimal wiring decision:** Do not modify `CatalogStore` or `app_state.py`. `main.py` already knows `CLIPATLAS_LIBRARY_DB`; it passes that path to the hybrid factory, which opens `ASRStore` and `OCRStore` on the same SQLite file. Visual search may be `None`.

- [x] Add runtime/API RED tests.
- [x] Add hybrid factory, app state attachment in `main.py`, and one route/protocol in the existing search router.
- [x] Run a target FastAPI behavior check: normal query 200; provenance fields returned; blank query 422.

### Task 5: Reverse audit and verification

- [ ] Compare P0-6 head to P0-5 production base `12ba8c17763e4ee0df942ae6cfd6d257f97c90c8`.
- [ ] Confirm no new tables, queues, embedding pipelines, FTS, reranker, frontend, deep-understanding, rough-cut, CatalogStore, or app-state changes.
- [ ] Re-check targeted ASR/OCR/hybrid/API behavior with fresh evidence.
- [ ] Run full Ruff/Mypy/Pytest/frontend CI when the execution environment can execute actual steps. If Actions remains `steps=null`, record infrastructure blockage and do not alter production code to chase it.
- [ ] Do not merge into the official active branch until full repository verification executes real steps and succeeds.

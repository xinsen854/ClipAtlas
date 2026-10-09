# Qwen Top-K Deep Pass P0-7 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure qwen3.8-flash runs only on Hybrid Recall Top-K candidates and feeds the existing RoughCut pipeline without adding a second provider, database, queue, scoring system, or public deep-search API.

**Architecture:** Disable qwen as a library-wide segment provider, add one in-memory `DeepPassService` that reuses `FrameExtractor` and `QwenVideoUnderstandingProvider`, widen the RoughCut search-hit type boundary structurally, then wire deep pass as the preferred internal RoughCut search with semantic-search fallback.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, existing ClipAtlas Hybrid Recall, FrameExtractor, QwenVideoUnderstandingProvider.

**Spec:** `docs/superpowers/specs/2026-09-05-qwen-top-k-deep-pass-design.md`

## Global Constraints

- qwen3.8-flash must not run in the whole-library ingestion loop.
- Explicit legacy `CLIPATLAS_LIBRARY_PROVIDER=qwen` resolves to no library deep provider and must not fall back to fake.
- No deep-pass DB/table/cache/revision/queue.
- No second Qwen provider class.
- No second frame extractor.
- No public `/api/v1/search/deep` endpoint.
- Default Top-K remains existing RoughCut `PlannerSettings.top_k = 12`.
- Formal Bailian credentials only for deep pass.
- Existing semantic-search fallback remains when deep pass is unavailable.
- TTS, ASR, OCR, video embeddings, OTIO, Jianying and frontend are out of scope.

---

### Task 1: Block qwen whole-library analysis

**Files:**
- Modify: `clipatlas/app_state.py`
- Test: `tests/library/test_qwen_deep_pass_gate.py`

**Interfaces:**
- Existing `_select_library_provider(registry)` remains private and returns `VideoUnderstandingProvider | None`.

- [ ] Write failing tests proving auto-selection never returns qwen, explicit `CLIPATLAS_LIBRARY_PROVIDER=qwen` does not re-enable qwen or fall back to fake, and fake provider remains selectable normally.
- [ ] Run focused tests and verify RED against current behavior.
- [ ] Make the minimum selection-policy change only; do not remove qwen from the provider registry.
- [ ] Run focused tests and require GREEN.

### Task 2: Extend Qwen prompt for retrieval context

**Files:**
- Modify: `clipatlas/providers/qwen.py`
- Test: `tests/providers/test_qwen_deep_pass_context.py`

**Interfaces:**
- Existing `AnalyzeSegmentRequest.context` carries `analysis_scope`, `query`, `asr_texts`, `ocr_texts`, and source scores.

- [ ] Write failing test asserting `top_k_deep_pass` request text labels query/ASR/OCR as retrieval context and explicitly says they are not visual facts.
- [ ] Verify RED.
- [ ] Extend only `_multimodal_content()` prompt construction; keep `QwenSemanticPayload` schema and HTTP path unchanged.
- [ ] Verify GREEN.

### Task 3: Add in-memory DeepPassService

**Files:**
- Create: `clipatlas/retrieval/deep_pass.py`
- Test: `tests/retrieval/test_deep_pass.py`

**Interfaces:**
- `DeepPassHit` fields: `segment_id`, `video_id`, `filename`, `source_uri`, `source_start_ms`, `source_end_ms`, `score`, `annotation`, `provider`, `model`, `sources`, `visual_score`, `asr_score`, `ocr_score`, `asr_texts`, `ocr_texts`.
- `DeepPassService.search(query, limit=12, video_ids=None) -> list[DeepPassHit]`.

- [ ] Write failing tests proving: Hybrid receives exact limit; candidate UUID is deterministic from video/time range; existing `FrameExtractor` is called with the candidate span; provider receives `analysis_scope="top_k_deep_pass"` plus retrieval context; returned annotation is preserved; successful temp frames are deleted.
- [ ] Verify RED because module/service is absent.
- [ ] Implement the minimum sequential service. Resolve only local `file://` sources; propagate unsupported-source/provider/frame failures. Do not add retry/concurrency/cache.
- [ ] Verify GREEN.

### Task 4: Widen RoughCut search-hit contract without changing scoring

**Files:**
- Modify: `clipatlas/roughcut/contracts.py`
- Modify: `clipatlas/roughcut/planner.py`
- Modify: `clipatlas/roughcut/scoring.py`
- Test: `tests/roughcut/test_search_contract.py`

**Interfaces:**
- Add structural `RoughCutSearchHit(Protocol)` containing only fields used by planner/scorer.
- `SegmentSearch.search()` returns `Sequence[RoughCutSearchHit]`.

- [ ] Write failing type/behavior-oriented test using a minimal non-`SemanticSearchHit` object with the required fields.
- [ ] Verify RED against current annotations/contract assumptions.
- [ ] Change only type boundaries/imports; do not alter score formulas, planner settings, timeline selection, store schema, or clip models.
- [ ] Verify GREEN.

### Task 5: Internal runtime wiring

**Files:**
- Modify: `clipatlas/app_state.py`
- Modify: `clipatlas/main.py`
- Test: `tests/retrieval/test_deep_pass_runtime.py`
- Test: `tests/api/test_deep_search.py`

**Interfaces:**
- `build_deep_pass_search_service(hybrid_service) -> DeepPassService | None` uses only formal Bailian key/base URL and existing cache root.
- `build_rough_cut_runtime(..., deep_pass_search_service=None)` prefers deep pass when present and otherwise uses existing semantic search.
- `/api/v1/search/deep` remains absent; `tests/api/test_deep_search.py` is a regression guard against accidentally exposing the internal service.

- [ ] Write failing tests for formal-Bailian-only builder, no-service without formal credentials, same library cache root, RoughCut deep-pass preference/fallback, and absence of a public deep route.
- [ ] Verify RED.
- [ ] Add minimum builder/state wiring without adding a public API.
- [ ] Verify GREEN.

### Task 6: Reverse audit and verification

**Files:** no production additions unless a test exposes a concrete defect.

- [ ] Compare P0-7 head to P0-6 base `95a79986513e94d996089b52a51ef41aed246e8b`.
- [ ] Confirm no DB schema, cache table, queue, second provider, second extractor, public deep-search route, frontend, TTS, ASR/OCR or export changes.
- [ ] Re-run focused P0-7 tests from fresh state.
- [ ] Run repository Ruff/Mypy/Pytest/frontend checks when execution environment permits.
- [ ] If Actions still reports `steps=null`, record infrastructure blockage and do not merge to the official active branch.

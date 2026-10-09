# SentrySearch Compatibility P0-3 Implementation Plan

> **Execution:** Use superpowers:executing-plans and TDD. Keep every change inside this P0-3 boundary.

**Goal:** Reuse the vendored SentrySearch Qwen request/retry/rate-limit core without creating a second ClipAtlas adapter layer or replacing the already-stable ClipAtlas index/checkpoint/materialization pipeline.

**Minimal architecture:** `clipatlas/embeddings/qwen_vl.py` is already the correct ClipAtlas adapter boundary. Keep the public class `QwenVLVideoEmbeddingProvider`, its `VideoEmbeddingProvider` contract, `app_state.py`, `CoarseVideoIndexer`, `VideoChunkMaterializer`, CatalogStore, checkpoints, search API, and UI unchanged. Replace only the handwritten DashScope call/retry core inside `QwenVLVideoEmbeddingProvider` with composition over the byte-locked vendored `QwenCloudEmbedder`.

**Why this is smaller:** Adding `clipatlas/integrations/sentrysearch_adapter.py` would duplicate the responsibility already owned by `clipatlas/embeddings/qwen_vl.py` and force an unnecessary runtime wiring change. P0-3 should reduce duplicated provider logic rather than add another layer.

## Locked boundaries

- Model default remains `qwen3-vl-embedding`.
- Effective dimensions remain 2560 and actual returned vector length is validated.
- 5s/1s remains default; 30s/5s remains optional; no 1s profile.
- Vendored SentrySearch files remain byte-identical to commit `a89d1282fe52dd98aa71593cda86f8e8b4fbdd3b`.
- No runtime SentrySearch DLQ/store/CLI/overlay/Gemini.
- No second checkpoint system, chunk planner, rate limiter, or retry loop.
- Keep current `VideoChunkMaterializer` until the later real-material blackbox cleanup gate.
- No `app_state.py`, frontend, TTS, ASR, OCR, Hybrid Recall, qwen3.8 deep-pass, RoughCut, OTIO, Jianying, or Human revision changes unless a failing regression test proves necessity.
- Unified Bailian key must never be left behind in `DASHSCOPE_API_KEY` merely to satisfy the vendored constructor.

---

## Task 1 — RED: lock vendor delegation on the existing provider

**Modify:** `tests/embeddings/test_qwen_vl.py`

Replace direct `multimodal_call`-centric tests with an injected fake vendored embedder factory. The new tests must require the existing provider to construct the vendor core with:

```python
model_name="qwen3-vl-embedding"
dimensions=2560
```

Tests must also require:

- `embed_video()` delegates to `embed_video_chunk()` asynchronously.
- `embed_query()` delegates to vendor `embed_query()`.
- missing local video fails before vendor invocation.
- a returned 768-length vector is rejected with `ProviderRequestError` mentioning 2560.
- non-finite/non-numeric values remain rejected.
- final vendor error text maps to existing ClipAtlas errors: 401/403 auth, 429/rate/throttle/quota rate-limit, all others request error.
- constructor temporarily exposes the ClipAtlas key as `DASHSCOPE_API_KEY` to the vendor factory and restores the exact previous environment state afterward, both when the variable was absent and when it had a previous value.

**RED gate:** Ruff and Mypy must pass; Pytest must fail because the current provider does not accept/use the vendor factory contract yet.

---

## Task 2 — GREEN: replace only the provider core

**Modify:** `clipatlas/embeddings/qwen_vl.py`

Keep class name and runtime-facing properties/methods unchanged. Remove the duplicated direct `MultiModalEmbedding.call`, HTTP response parsing, and handwritten request handling that the vendor now owns.

Implementation requirements:

1. Accept a small optional `embedder_factory` dependency-injection hook for tests; production defaults to the vendored `QwenCloudEmbedder`.
2. Save whether `DASHSCOPE_API_KEY` existed and its exact previous value before loading/constructing the vendor core.
3. Temporarily set the ClipAtlas API key during vendor module load/construction, then restore the exact prior environment state in `finally`.
4. Preserve the existing native DashScope base-URL behavior for Workspace `/api/v1`.
5. Construct the vendor core with the selected model and `dimensions=2560`.
6. Use `asyncio.to_thread` for the synchronous vendor `embed_video_chunk` / `embed_query` calls.
7. Do not add another retry/rate-limit layer; vendor `_retry` / `_RateLimiter` stay authoritative.
8. Validate returned vector length and numeric finiteness before creating `EmbeddingVector`.
9. Normalize final vendor/dependency/transport exceptions into the existing ClipAtlas provider error taxonomy.

**Focused GREEN gate:**

```text
pytest tests/embeddings/test_qwen_vl.py tests/test_video_embedding_runtime.py tests/test_app_state.py tests/vendor/test_sentrysearch_vendor.py -q
```

---

## Task 3 — Regression gate for the existing index pipeline

No production changes expected.

Run and preserve:

```text
pytest tests/retrieval/test_video_indexer.py tests/retrieval/test_video_index_profiles.py tests/video/test_chunk_materializer.py tests/library/test_worker_video_indexing.py -q
```

This proves that P0-3 did not create a second index state machine or alter 5s/30s/checkpoint/materialization semantics.

---

## Task 4 — Full verification and reverse audit

1. Full CI must pass: Ruff, Mypy, Pytest, Frontend Tests, Frontend Typecheck, Frontend Build.
2. `tests/vendor/test_sentrysearch_vendor.py` must confirm vendored blob SHAs are unchanged.
3. Compare against base `06246f873cdb4556a85fb37aa30b3fe44c651036`.
4. Expected production diff is only:

```text
clipatlas/embeddings/qwen_vl.py
```

plus tests and this plan. Any additional production file is presumptively over-scope.
5. Explicitly confirm no runtime DLQ/store/chunker duplication, no frontend, no TTS/ASR/OCR/Hybrid Recall/deep-pass changes, and no vendor edits.
6. Fast-forward `feat/video-index-profiles-v0.1-active` only if it is still at the expected base and the isolated branch is fully green. Never force the active branch.
7. Require a fresh full CI success on the active branch before declaring P0-3 complete.

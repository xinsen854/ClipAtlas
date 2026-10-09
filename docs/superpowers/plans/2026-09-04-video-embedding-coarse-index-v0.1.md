# Video Embedding Coarse Index V0.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an isolated qwen3-vl video-vector foundation with 30-second coarse chunk planning and chunk-level persistence/checkpoints without changing the existing text semantic pipeline.

**Architecture:** Keep the existing annotation/text embedding path untouched. Introduce a separate video embedding protocol/provider, a deterministic chunk planner, a dedicated SQLite table/model for 2560-dimensional video chunk vectors, and an independent checkpoint store keyed by video/time/provider/model.

**Tech Stack:** Python 3.12, Pydantic 2, SQLite, pytest/pytest-asyncio, DashScope Python SDK as an optional extra.

**Spec:** `docs/superpowers/specs/2026-09-04-video-embedding-coarse-index-v0.1-design.md`

## Global Constraints

- qwen3-vl-embedding effective dimension is 2560; actual response length must be validated.
- Existing `text-embedding-v4` / 1024-dimensional segment embeddings remain unchanged.
- 30-second coarse chunks use 5-second overlap.
- No OCR, ASR, 5-second refinement, frontend, rough-cut, OTIO, Jianying, or library worker rewiring in this batch.
- No API keys may be logged or persisted.

---

### Task 1: Dedicated video embedding contract and model

**Files:**
- Modify: `clipatlas/embeddings/contracts.py`
- Modify: `clipatlas/embeddings/__init__.py`
- Modify: `clipatlas/retrieval/models.py`
- Test: `tests/embeddings/test_embedding_contracts.py`
- Test: `tests/retrieval/test_indexer.py`

**Interfaces:**
- Produces: `VideoEmbeddingProvider`, `VideoChunkEmbedding`

- [ ] **Step 1: Write failing tests**

Add tests that define a runtime-conforming fake video provider with `effective_dimensions`, `embed_video(Path)`, and `embed_query(str)`. Add model tests proving `VideoChunkEmbedding` accepts a 2560-value vector and rejects dimension mismatches.

- [ ] **Step 2: Run targeted tests and verify RED**

Run:
`pytest tests/embeddings/test_embedding_contracts.py tests/retrieval/test_indexer.py -q`

Expected: FAIL because `VideoEmbeddingProvider` and `VideoChunkEmbedding` do not exist.

- [ ] **Step 3: Implement minimal contract/model**

Add:

```python
@runtime_checkable
class VideoEmbeddingProvider(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def model(self) -> str: ...
    @property
    def effective_dimensions(self) -> int: ...
    async def embed_video(self, video_path: Path) -> EmbeddingVector: ...
    async def embed_query(self, text: str) -> EmbeddingVector: ...
```

Add `VideoChunkEmbedding` with `video_id`, `start_ms`, `end_ms`, provider/model/dimensions/vector and validation that `end_ms > start_ms` and vector length matches dimensions.

- [ ] **Step 4: Re-run tests and verify GREEN**

- [ ] **Step 5: Commit**

Commit message: `feat: add video embedding contracts`

---

### Task 2: qwen3-vl DashScope adapter

**Files:**
- Create: `clipatlas/embeddings/qwen_vl.py`
- Modify: `clipatlas/embeddings/__init__.py`
- Modify: `pyproject.toml`
- Create: `tests/embeddings/test_qwen_vl.py`

**Interfaces:**
- Produces: `QwenVLVideoEmbeddingProvider`
- Default model: `qwen3-vl-embedding`
- Effective dimensions: `2560`

- [ ] **Step 1: Write failing tests**

Tests use a fake `MultiModalEmbedding.call` dependency injected into the provider, so no network or key output is needed. Cover:
- video success returns 2560 values
- text query success returns 2560 values
- returned 768-vector raises `ProviderRequestError`
- nonexistent local video raises `FileNotFoundError`
- HTTP 401/403 -> `ProviderAuthenticationError`
- HTTP 429 -> `ProviderRateLimitError`
- other non-200 -> `ProviderRequestError`

- [ ] **Step 2: Verify RED**

Run: `pytest tests/embeddings/test_qwen_vl.py -q`
Expected: FAIL because module/provider does not exist.

- [ ] **Step 3: Implement minimal adapter**

Constructor accepts `api_key`, optional model, and optional injected multimodal client/callable. Production fallback lazily imports `dashscope.MultiModalEmbedding`; missing optional dependency raises a clear configuration `ValueError`/provider error without affecting installations that never instantiate this provider.

Call forms:

```python
input=[{"video": str(video_path), "factor": 1.0}]
parameters={}
```

and

```python
input=[{"text": text, "factor": 1.0}]
parameters={}
```

Do not request a fake 768 dimension. Parse `output.embeddings[0].embedding`, validate 2560 finite numeric values.

Add optional dependency:

```toml
video-embedding = ["dashscope>=1.25.17,<2"]
```

- [ ] **Step 4: Verify GREEN**

- [ ] **Step 5: Commit**

Commit message: `feat: add qwen vl video embedding provider`

---

### Task 3: 30-second coarse chunk planner

**Files:**
- Create: `clipatlas/video/chunks.py`
- Modify: `clipatlas/video/__init__.py`
- Create: `tests/video/test_chunks.py`

**Interfaces:**
- Produces: `VideoChunkSpan(start_ms: int, end_ms: int)` and `plan_video_chunks(duration_ms, chunk_duration_ms=30000, overlap_ms=5000)`

- [ ] **Step 1: Write failing tests**

Cover:
- 10-second video -> one `0..10000` span
- 70-second video -> `0..30000`, `25000..55000`, `50000..70000`
- exact 30-second video -> one span
- overlap >= duration rejects
- non-positive duration/chunk rejects
- negative overlap rejects

- [ ] **Step 2: Verify RED**

Run: `pytest tests/video/test_chunks.py -q`
Expected: FAIL because module does not exist.

- [ ] **Step 3: Implement pure planner**

No ffmpeg invocation and no filesystem writes in this task.

- [ ] **Step 4: Verify GREEN**

- [ ] **Step 5: Commit**

Commit message: `feat: add coarse video chunk planner`

---

### Task 4: Separate video chunk vector persistence

**Files:**
- Modify: `clipatlas/catalog/store.py`
- Create: `tests/catalog/test_video_chunk_embedding_store.py`

**Interfaces:**
- Produces methods:
  - `save_video_chunk_embedding(record: VideoChunkEmbedding) -> None`
  - `get_video_chunk_embedding(video_id, start_ms, end_ms, provider, model, dimensions) -> VideoChunkEmbedding | None`
  - `list_video_chunk_embeddings(video_id, provider, model, dimensions) -> list[VideoChunkEmbedding]`

- [ ] **Step 1: Write failing tests**

Test that:
- a video chunk vector persists and reloads exactly
- duplicate unique key replaces/updates the vector rather than producing two effective rows
- a 2560 video chunk vector can coexist with an existing 1024 segment embedding without changing/deactivating that segment embedding
- listing is ordered by start/end

- [ ] **Step 2: Verify RED**

Run: `pytest tests/catalog/test_video_chunk_embedding_store.py -q`
Expected: FAIL because methods/table do not exist.

- [ ] **Step 3: Implement minimal table and methods**

Create `catalog_video_chunk_embeddings` with a unique index over `(video_id,start_ms,end_ms,provider,model,dimensions)` and no annotation foreign key.

- [ ] **Step 4: Verify GREEN**

- [ ] **Step 5: Commit**

Commit message: `feat: persist video chunk embeddings separately`

---

### Task 5: Chunk-level checkpoints

**Files:**
- Modify: `clipatlas/catalog/checkpoints.py`
- Create: `tests/catalog/test_video_chunk_checkpoints.py`

**Interfaces:**
- Produces `VideoChunkCheckpointStatus` enum and `VideoChunkCheckpointStore` with:
  - `mark_processing(...)`
  - `mark_completed(...)`
  - `mark_failed(..., error: str)`
  - `get(...)`
  - `is_completed(...)`

- [ ] **Step 1: Write failing tests**

Cover:
- initial missing checkpoint is not completed
- processing increments attempt_count
- completed is reusable
- failed preserves error and can transition back to processing with incremented attempt count
- prepared-media checkpoint behavior remains unchanged

- [ ] **Step 2: Verify RED**

Run: `pytest tests/catalog/test_video_chunk_checkpoints.py tests/catalog/test_embedding_store.py -q`
Expected: FAIL only on new checkpoint tests.

- [ ] **Step 3: Implement minimal checkpoint store**

Use the same SQLite file but a distinct `catalog_video_chunk_checkpoints` table. No changes to `PreparedMediaCheckpointStore` public behavior.

- [ ] **Step 4: Verify GREEN**

- [ ] **Step 5: Commit**

Commit message: `feat: add video chunk checkpoints`

---

### Task 6: Integration verification for first batch

**Files:**
- No production expansion beyond fixes required by tests.

- [ ] **Step 1: Run focused backend tests**

`pytest tests/embeddings tests/video/test_chunks.py tests/catalog/test_video_chunk_embedding_store.py tests/catalog/test_video_chunk_checkpoints.py -q`

- [ ] **Step 2: Run full backend suite**

`pytest -q`

- [ ] **Step 3: Run static checks**

`ruff check .`

`mypy clipatlas`

- [ ] **Step 4: Review diff against scope**

Confirm no modifications to frontend, library worker/supervisor behavior, OCR/ASR, roughcut, TTS, OTIO/Jianying, or existing text embedding semantics.

- [ ] **Step 5: Commit any verification-only corrections**

Commit message if needed: `fix: harden video embedding foundation`

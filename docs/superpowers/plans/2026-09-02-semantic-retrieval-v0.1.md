# Semantic Retrieval V0.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn persisted ClipAtlas segment annotations into provider-neutral semantic search hits that contain exact source video ranges and immediately respect human corrections.

**Architecture:** Resolve one effective annotation per canonical segment (latest human revision wins, otherwise latest AI), build deterministic retrieval text, embed it through a separate `EmbeddingProvider`, persist versioned vectors in SQLite, and perform V0.1 cosine search behind a storage-neutral retrieval service. Search results always return ClipAtlas `video_id`, `segment_id`, `source_uri`, and exact `start_ms/end_ms`; later ScriptBeat planning consumes the same interface without knowing SQLite or Qwen details.

**Tech Stack:** Python 3.12, Pydantic 2, SQLite, httpx, FastAPI, pytest, Ruff, strict Mypy. Default Alibaba embedding model: `text-embedding-v4`, 1024 dimensions; model/base URL are configurable.

**Spec:** `docs/superpowers/specs/2026-09-02-script-driven-rough-cut-design.md`

## Global Constraints

- Human correction is retrieval-authoritative: newest human annotation wins over AI, while historical AI/human records remain immutable.
- PySceneDetect/FFmpeg `VideoSegment.start_ms/end_ms` remain edit-boundary authority; embeddings never create or replace time boundaries.
- Embedding provider/model/dimensions are metadata, not canonical segment identity.
- Default embedding model is `text-embedding-v4` with 1024 dimensions; configuration may select another compatible model.
- V0.1 uses SQLite serialized vectors + linear cosine search; planner-facing interfaces must remain replaceable by pgvector later.
- Unchanged effective semantics under the same provider/model/dimensions must not be re-embedded.
- All changes use TDD and must preserve Ruff, strict Mypy, and the complete pytest suite.

---

### Task 1: Effective semantic authority and deterministic retrieval text

**Files:**
- Create: `clipatlas/retrieval/__init__.py`
- Create: `clipatlas/retrieval/semantics.py`
- Test: `tests/retrieval/test_semantics.py`
- Modify: `clipatlas/catalog/store.py`

**Interfaces:**
- Consumes: `SemanticAnnotation`, `AnnotationOrigin`, persisted annotation revisions.
- Produces: `EffectiveSemantics(annotation: SemanticAnnotation, text: str)`; `build_retrieval_text(annotation) -> str`; `CatalogStore.get_effective_annotation(segment_id) -> SemanticAnnotation | None`.

- [ ] **Step 1: Write failing tests** proving latest human revision wins, AI is used when no human exists, and retrieval text follows the deterministic field order `description → characters → actions → scene → emotions → objects → OCR → shot type → camera motion` while omitting empty fields.

```python
annotation = SemanticAnnotation(
    segment_id=segment_id,
    origin=AnnotationOrigin.HUMAN,
    description="男人站在雨夜街口",
    actions=["等待"],
    scene=["城市雨夜"],
    emotions=["孤独"],
)
assert build_retrieval_text(annotation) == (
    "男人站在雨夜街口\nactions: 等待\nscene: 城市雨夜\nemotions: 孤独"
)
```

- [ ] **Step 2: Run RED** with `pytest tests/retrieval/test_semantics.py -v`; expected failure is missing retrieval semantic resolver/store method.
- [ ] **Step 3: Implement minimal resolver/text builder** and a SQL query in `CatalogStore` ordered by origin authority, revision descending, then created time/rowid descending.
- [ ] **Step 4: Run GREEN** for the focused tests, then `ruff check .` and `mypy clipatlas`.
- [ ] **Step 5: Commit** `feat: resolve effective segment semantics`.

---

### Task 2: Provider-neutral embedding contract and Alibaba adapter

**Files:**
- Create: `clipatlas/embeddings/__init__.py`
- Create: `clipatlas/embeddings/contracts.py`
- Create: `clipatlas/embeddings/qwen.py`
- Test: `tests/embeddings/test_contracts.py`
- Test: `tests/embeddings/test_qwen.py`

**Interfaces:**
- Produces:
  - `EmbeddingVector(values: list[float])`
  - runtime-checkable `EmbeddingProvider` with `name`, `model`, `dimensions`, `embed_documents(texts)`, `embed_query(text)`.
  - `QwenTextEmbeddingProvider(api_key, base_url, model="text-embedding-v4", dimensions=1024, ...)`.

- [ ] **Step 1: Write failing contract tests** for provider runtime compatibility and vector dimension validation.
- [ ] **Step 2: Write failing HTTP tests** using `httpx.MockTransport`; require `POST {base_url}/embeddings` with `model`, `input`, and `dimensions`, preserve result order, and normalize 401/403/429/other HTTP failures into existing provider error classes.

```python
assert request.url.path.endswith("/embeddings")
body = json.loads(request.content)
assert body == {
    "model": "text-embedding-v4",
    "input": ["雨夜独行", "城市人群"],
    "dimensions": 1024,
}
```

- [ ] **Step 3: Run RED**; expected failure is missing embedding package/provider.
- [ ] **Step 4: Implement the minimal adapter** with async httpx, strict response parsing, finite numeric vector validation, stable dimensions, and no OpenAI SDK dependency.
- [ ] **Step 5: Run GREEN + Ruff + Mypy**.
- [ ] **Step 6: Commit** `feat: add provider-neutral text embeddings`.

---

### Task 3: Versioned embedding persistence in CatalogStore

**Files:**
- Modify: `clipatlas/catalog/store.py`
- Create: `clipatlas/retrieval/models.py`
- Test: `tests/catalog/test_embedding_store.py`

**Interfaces:**
- Produces:
  - `SegmentEmbedding` containing segment/annotation/provider/model/dimensions/vector/effective flag/timestamp.
  - `CatalogStore.save_embedding(record)`
  - `CatalogStore.get_effective_embedding(segment_id, provider, model, dimensions)`
  - `CatalogStore.list_effective_embeddings(provider, model, dimensions)`
  - `CatalogStore.deactivate_segment_embeddings(segment_id)`.

- [ ] **Step 1: Write failing persistence tests** proving vectors survive DB reopen, only one record is effective for a segment, old records remain for audit, and provider/model/dimension changes do not collide.
- [ ] **Step 2: Run RED**; expected failure is missing embedding table/model/store methods.
- [ ] **Step 3: Add SQLite schema** `catalog_embeddings` with serialized JSON float vector, annotation identity/revision, provider/model/dimensions, `effective`, and created timestamp; add indexes for segment/effective/provider/model/dimensions.
- [ ] **Step 4: Implement methods transactionally** so activating a new vector first deactivates older effective vectors for that segment but never deletes them.
- [ ] **Step 5: Run GREEN + full catalog tests**.
- [ ] **Step 6: Commit** `feat: persist versioned segment embeddings`.

---

### Task 4: Incremental semantic indexer

**Files:**
- Create: `clipatlas/retrieval/indexer.py`
- Test: `tests/retrieval/test_indexer.py`

**Interfaces:**
- Consumes: `CatalogStore`, `EmbeddingProvider`, effective semantic resolver.
- Produces: `SemanticIndexer.index_segment(segment_id) -> bool` where `True` means a new embedding was generated; `index_pending(limit=None) -> int`.

- [ ] **Step 1: Write failing tests** covering AI-only indexing, unchanged segment skip, human correction reindex, model/dimension change reindex, and missing annotation skip.
- [ ] **Step 2: Run RED**.
- [ ] **Step 3: Implement signature comparison** using effective annotation ID/revision + provider name/model/dimensions; only call the API when the active embedding signature differs.
- [ ] **Step 4: Ensure human correction behavior**: effective human annotation creates a new active vector while AI annotation and old vector remain stored.
- [ ] **Step 5: Run GREEN + Ruff + Mypy**.
- [ ] **Step 6: Commit** `feat: add incremental semantic indexer`.

---

### Task 5: Cosine retrieval with exact source ranges

**Files:**
- Create: `clipatlas/retrieval/search.py`
- Modify: `clipatlas/catalog/store.py`
- Test: `tests/retrieval/test_search.py`

**Interfaces:**
- Produces:
  - `SemanticSearchHit(segment_id, video_id, source_uri, source_start_ms, source_end_ms, score, effective_description, annotation, embedding metadata)`.
  - `SemanticSearchService.search(query: str, limit: int = 10, video_ids: list[UUID] | None = None) -> list[SemanticSearchHit]`.

- [ ] **Step 1: Write failing deterministic tests** with a fake embedding provider and known vectors; require descending cosine score, `limit`, optional video filtering, and exact canonical source times.

```python
hit = hits[0]
assert hit.source_start_ms == segment.start_ms
assert hit.source_end_ms == segment.end_ms
assert hit.source_uri == video.source_uri
```

- [ ] **Step 2: Run RED**.
- [ ] **Step 3: Implement safe cosine similarity** returning no match for invalid/zero-norm stored vectors rather than dividing by zero.
- [ ] **Step 4: Join catalog video/segment/effective annotation data** without allowing embedding/provider timestamps to alter source boundaries.
- [ ] **Step 5: Run GREEN + full retrieval tests**.
- [ ] **Step 6: Commit** `feat: search semantic footage by exact segment range`.

---

### Task 6: Retrieval API and runtime configuration

**Files:**
- Create: `clipatlas/api/routes/search.py`
- Modify: `clipatlas/main.py`
- Modify: `clipatlas/app_state.py`
- Modify: `.env.example`
- Test: `tests/api/test_search.py`
- Test: `tests/test_app_state.py`

**Interfaces:**
- API: `GET /api/v1/search/segments?q=<text>&limit=10`.
- Runtime config:
  - `CLIPATLAS_EMBEDDING_API_KEY` falling back to `DASHSCOPE_API_KEY`.
  - `CLIPATLAS_EMBEDDING_BASE_URL` falling back to existing Qwen compatible base URL.
  - `CLIPATLAS_EMBEDDING_MODEL=text-embedding-v4`.
  - `CLIPATLAS_EMBEDDING_DIMENSIONS=1024`.

- [ ] **Step 1: Write failing API tests** that inject a fake search service and verify query validation, limit bounds, JSON fields, and exact source time ranges.
- [ ] **Step 2: Write failing app-state tests** proving embedding/search runtime is enabled only with an embedding key and invalid dimensions fail fast.
- [ ] **Step 3: Run RED**.
- [ ] **Step 4: Wire runtime** using the same SQLite catalog DB and a Qwen text embedding provider; expose the search service in app state and register the router.
- [ ] **Step 5: Keep indexing independently callable**; do not block FastAPI startup by bulk-embedding an entire existing library.
- [ ] **Step 6: Run GREEN + Ruff + Mypy**.
- [ ] **Step 7: Commit** `feat: expose semantic footage search API`.

---

### Task 7: Automatic indexing after semantic analysis and final verification

**Files:**
- Modify: `clipatlas/library/worker.py`
- Modify: `clipatlas/app_state.py`
- Modify: `README.md`
- Test: `tests/library/test_semantic_worker.py`
- Test: `tests/retrieval/test_worker_indexing.py`

**Interfaces:**
- `SequentialLibraryWorker` receives an optional indexer-like dependency with `index_segment(segment_id) -> Awaitable[bool]` or an async-compatible wrapper.
- After each successfully persisted semantic annotation, the affected segment is indexed; an embedding failure fails that item and retry resumes without re-running completed video preparation/semantic analysis.

- [ ] **Step 1: Write failing worker tests** proving semantic save happens before indexing, existing semantics are not regenerated after an embedding failure, retry only indexes missing/stale vectors, and one failed video remains isolated from the queue.
- [ ] **Step 2: Run RED**.
- [ ] **Step 3: Add the minimal worker hook** after annotation persistence and for already-annotated segments whose embedding is absent/stale.
- [ ] **Step 4: Update README** with the pipeline `scan → segment → semantic annotation → effective semantics → embedding → search`, config variables, and the future planner contract.
- [ ] **Step 5: Run final verification**: `ruff check .`, `mypy clipatlas`, `pytest -v`.
- [ ] **Step 6: Confirm all six Semantic Retrieval acceptance criteria** from the spec against tests.
- [ ] **Step 7: Commit** `feat: complete semantic retrieval v0.1`.

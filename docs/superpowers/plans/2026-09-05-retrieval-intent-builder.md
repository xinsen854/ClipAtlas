# Retrieval Intent Builder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert abstract narration beats into a small set of camera-observable search expressions before Hybrid Recall, while preserving the existing Hybrid → Top-K DeepPass → RoughCut pipeline.

**Architecture:** Add a small Bailian text-only structured intent builder plus an `IntentAwareHybridSearch` wrapper. The wrapper expands the original query, runs the existing Hybrid search for the original text and up to four visual queries, deduplicates identical candidate ranges by keeping the best existing Hybrid score, and returns only the requested Top-K to the existing DeepPass service. This intentionally sits *before* DeepPass so query expansion does not multiply qwen3.8 visual-analysis calls.

**Tech Stack:** Python 3.11+, Pydantic v2, httpx, pytest/pytest-asyncio, existing Bailian OpenAI-compatible endpoint.

**Spec:** `docs/superpowers/specs/2026-09-05-retrieval-intent-builder-design.md`

## Global Constraints

- Do not add a new database, table, queue, checkpoint, cache, retry planner, or persistent footage-semantic index.
- Do not change ASR/OCR/Visual ingestion, Hybrid scoring, DeepPass scoring, RoughCut scoring/timeline, OTIO, or Jianying.
- Do not hard-code automotive/domain keyword mappings.
- Raw narration remains canonical and unmodified.
- Intent generation is ephemeral and fails open to the existing original-query path.
- Expansion must happen before DeepPass so the final DeepPass candidate count remains bounded by the existing `limit`.
- Reuse `CLIPATLAS_BAILIAN_API_KEY` and `CLIPATLAS_BAILIAN_BASE_URL`; never fall back to legacy third-party Qwen credentials.
- Default intent model is `qwen3.8-flash`; no new UI/model selector in V0.1.
- Maximum generated visual queries: 4, to bound extra Hybrid requests.
- Batch Rule Pack is not implemented in this plan.

---

### Task 1: Structured Retrieval Intent Builder

**Files:**
- Create: `clipatlas/retrieval/intent.py`
- Create: `tests/retrieval/test_intent_builder.py`

**Interfaces:**
- Produces `RetrievalIntent(source_text: str, meaning: list[str], visual_queries: list[str], entities: list[str])`.
- Produces protocol `RetrievalIntentBuilder.build(source_text: str, context: dict[str, object] | None = None) -> RetrievalIntent`.
- Produces `QwenRetrievalIntentBuilder(api_key: str, base_url: str, model: str = "qwen3.8-flash", ...)`.
- The provider calls `<base_url>/chat/completions` with strict structured output and never mutates `source_text` from model output.

- [ ] **Step 1: Write failing model/provider tests**

Tests must assert:

```python
@pytest.mark.asyncio
async def test_qwen_intent_builder_returns_observable_generic_intent(...):
    # Mock a structured response for a generic abstract statement.
    # Assert source_text is exactly the caller input.
    # Assert visual_queries and entities come from validated structured output.

@pytest.mark.asyncio
async def test_qwen_intent_builder_rejects_invalid_structured_output(...):
    # Invalid JSON/schema must raise ProviderRequestError.

@pytest.mark.asyncio
async def test_qwen_intent_builder_uses_only_supplied_bailian_endpoint(...):
    # Assert the request URL is the supplied formal Bailian OpenAI-compatible URL.
```

Use generic examples from different domains; production code must contain no domain map.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
python -m pytest tests/retrieval/test_intent_builder.py -q
```

Expected: collection/import failure because `clipatlas.retrieval.intent` does not yet exist.

- [ ] **Step 3: Implement the minimum builder**

`clipatlas/retrieval/intent.py` should contain:

```python
class RetrievalIntent(BaseModel):
    source_text: str
    meaning: list[str] = Field(default_factory=list)
    visual_queries: list[str] = Field(default_factory=list, max_length=4)
    entities: list[str] = Field(default_factory=list)

class RetrievalIntentBuilder(Protocol):
    async def build(
        self,
        source_text: str,
        context: dict[str, object] | None = None,
    ) -> RetrievalIntent: ...
```

Use a private strict Pydantic response payload for `meaning`, `visual_queries`, and `entities`; set `source_text` from the original caller input after validation. Prompt rules must be generic: preserve stated facts, derive audience meaning, translate abstract meaning to camera-observable events/states/environments/interactions, preserve useful named entities, avoid invented concrete facts, and output at most four complementary visual queries.

Do not add retries or persistence.

- [ ] **Step 4: Run builder tests and verify GREEN**

```powershell
python -m pytest tests/retrieval/test_intent_builder.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add clipatlas/retrieval/intent.py tests/retrieval/test_intent_builder.py
git commit -m "feat: add retrieval intent builder"
```

---

### Task 2: Intent-Aware Hybrid Query Expansion

**Files:**
- Create: `clipatlas/retrieval/intent_search.py`
- Create: `tests/retrieval/test_intent_search.py`

**Interfaces:**
- Consumes `RetrievalIntentBuilder` from Task 1.
- Consumes the existing Hybrid `search(query, limit, video_ids)` contract.
- Produces `IntentAwareHybridSearch`, compatible with `DeepPassService`'s `HybridSearchLike` protocol.

- [ ] **Step 1: Write failing wrapper tests**

Tests must cover:

```python
@pytest.mark.asyncio
async def test_intent_search_keeps_original_query_and_adds_visual_queries():
    # Underlying search records calls.
    # Assert original query is always called first.
    # Assert each unique visual query is also called.

@pytest.mark.asyncio
async def test_intent_search_deduplicates_same_candidate_and_keeps_best_existing_hit():
    # Same (video_id, start_ms, end_ms) appears for multiple query variants.
    # Assert one result remains and it is the hit with the greatest existing score.
    # Do not synthesize a new score.

@pytest.mark.asyncio
async def test_intent_search_limits_results_before_deep_pass():
    # Expanded searches may return many hits.
    # Assert wrapper returns at most caller limit.

@pytest.mark.asyncio
async def test_intent_search_fails_open_when_builder_raises():
    # Builder raises ProviderRequestError.
    # Assert underlying search is called exactly once with original query.

@pytest.mark.asyncio
async def test_intent_search_uses_original_only_for_empty_visual_queries():
    # Builder returns no usable visual queries.
    # Assert only original query is searched.
```

- [ ] **Step 2: Run tests and verify RED**

```powershell
python -m pytest tests/retrieval/test_intent_search.py -q
```

Expected: import failure because `intent_search.py` does not exist.

- [ ] **Step 3: Implement minimal wrapper**

Required behaviour:

```python
class IntentAwareHybridSearch:
    def __init__(self, *, search: HybridSearchLike, builder: RetrievalIntentBuilder) -> None: ...

    async def search(self, query: str, limit: int = 10, video_ids: list[UUID] | None = None) -> list[HybridSearchHit]:
        ...
```

Algorithm:

1. Preserve existing blank/limit/video-id behaviour by delegating appropriately.
2. Build intent once.
3. Query list is original query plus non-empty unique `visual_queries`, capped by the model at four.
4. Call existing Hybrid search for each query with the caller's same `limit` and `video_ids`.
5. Deduplicate by `(video_id, source_start_ms, source_end_ms)`.
6. For duplicates, keep the complete `HybridSearchHit` object with the greatest existing `.score`; do not recompute or add scores.
7. Sort by existing score descending with deterministic range/id tie-breakers and return `[:limit]`.
8. On any intent-builder exception, call existing search once using only the original query.

Do not catch exceptions from the underlying Hybrid search; existing retrieval failures must remain visible.

- [ ] **Step 4: Run wrapper tests and verify GREEN**

```powershell
python -m pytest tests/retrieval/test_intent_search.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add clipatlas/retrieval/intent_search.py tests/retrieval/test_intent_search.py
git commit -m "feat: expand hybrid search with retrieval intent"
```

---

### Task 3: Runtime Wiring Before DeepPass

**Files:**
- Modify: `clipatlas/app_state.py`
- Modify: `clipatlas/main.py`
- Create: `tests/retrieval/test_intent_runtime.py`
- Verify unchanged: `clipatlas/retrieval/deep_pass.py`
- Verify unchanged: `clipatlas/roughcut/planner.py`

**Interfaces:**
- Produces `build_retrieval_intent_builder() -> RetrievalIntentBuilder | None` using only formal Bailian credentials.
- Produces `build_intent_aware_hybrid_search_service(hybrid_search_service, builder=None)` or equivalent narrow helper.
- `create_app()` wires the intent-aware Hybrid service into `build_deep_pass_search_service(...)`.

- [ ] **Step 1: Write failing runtime tests**

Tests must assert:

```python
def test_intent_builder_requires_formal_bailian_credentials(monkeypatch):
    # Legacy CLIPATLAS_QWEN_API_KEY alone must not create the builder.
    # Formal CLIPATLAS_BAILIAN_API_KEY + BASE_URL must create it.


def test_intent_wrapper_is_inserted_before_deep_pass(...):
    # Build or inspect runtime wiring.
    # Assert DeepPass._hybrid is IntentAwareHybridSearch when builder is available.
    # Assert DeepPass itself remains one service, not one per query variant.


def test_runtime_falls_back_to_plain_hybrid_without_intent_builder(...):
    # Missing formal credentials or explicitly unavailable builder.
    # Assert current Hybrid -> DeepPass path still works unchanged.
```

- [ ] **Step 2: Run runtime tests and verify RED**

```powershell
python -m pytest tests/retrieval/test_intent_runtime.py -q
```

Expected: missing builder/wiring symbols.

- [ ] **Step 3: Implement minimal runtime wiring**

Use the existing settings startup behaviour (`SettingsStore.apply_missing_environment()`) so saved Bailian configuration continues to populate the same formal environment variables before builders run.

`build_retrieval_intent_builder()`:

```python
api_key = os.getenv("CLIPATLAS_BAILIAN_API_KEY", "").strip()
base_url = os.getenv("CLIPATLAS_BAILIAN_BASE_URL", "").strip()
if not api_key or not base_url:
    return None
endpoints = derive_bailian_endpoints(base_url)
return QwenRetrievalIntentBuilder(
    api_key=api_key,
    base_url=endpoints.openai_compatible,
)
```

In `create_app()`:

```text
plain Hybrid
→ optional IntentAwareHybridSearch
→ existing build_deep_pass_search_service
→ existing RoughCut runtime
```

Do not change `DeepPassService` or `RoughCutPlanner` implementation.

- [ ] **Step 4: Run focused runtime/retrieval tests**

```powershell
python -m pytest \
  tests/retrieval/test_intent_builder.py \
  tests/retrieval/test_intent_search.py \
  tests/retrieval/test_intent_runtime.py \
  tests/retrieval/test_deep_pass.py \
  tests/retrieval/test_deep_pass_runtime.py \
  tests/retrieval/test_hybrid_search.py \
  tests/roughcut \
  -q
```

Expected: all pass.

- [ ] **Step 5: Reverse-audit the diff**

Confirm:

```text
No DB/schema changes
No Hybrid scoring changes
No DeepPass implementation changes
No RoughCut implementation changes
No OCR/ASR/Visual changes
No automotive/domain lookup table
No retry/cache/queue added
No query expansion after DeepPass
```

- [ ] **Step 6: Commit**

```bash
git add clipatlas/app_state.py clipatlas/main.py tests/retrieval/test_intent_runtime.py
git commit -m "feat: wire retrieval intent before deep pass"
```

---

### Task 4: Real Second-Creation Black-Box Acceptance

**Files:**
- No production changes unless real evidence exposes a bug.

- [ ] **Step 1: Pull the final branch locally and run the focused suite**

Use the existing Windows venv. Avoid raw Chinese in PowerShell-to-Python stdin; use Unicode escapes when needed.

- [ ] **Step 2: Run one abstract narration query against existing indexed material**

Acceptance is not exact word overlap. Capture:

```text
source_text
meaning
visual_queries
Hybrid candidates after expansion
DeepPass final candidate descriptions
```

- [ ] **Step 3: Evaluate product-level success**

Pass if the system can retrieve visually suitable footage for an abstract narration beat even when the footage does not literally contain the narration wording, while exact entity/ASR/OCR anchors still remain available through the original-query search.

- [ ] **Step 4: Do not tune from a single example unless there is a reproducible failure**

If the result is weak, inspect generated intent and candidate provenance first. Do not add domain rules or scoring changes without repeated evidence.

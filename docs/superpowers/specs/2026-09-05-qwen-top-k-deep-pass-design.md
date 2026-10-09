# Qwen Top-K Deep Pass P0-7 Design

Date: 2026-09-05

## Goal

Move qwen3.8-flash out of the library-wide ingestion path and use it only after Hybrid Recall has produced Top-K timeline candidates.

## Non-goals

P0-7 does not add a second Qwen provider, a deep-pass database/table, a reranker, a new Top-K setting, a second frame extractor, OSS upload, full-video deep analysis, frontend UI, public deep-search API, or new rough-cut scoring rules.

## Required behavior

1. Library ingestion must continue to build visual embeddings, ASR, OCR, checkpoints, and legacy semantic embeddings as configured, but qwen3.8-flash must not be selected as the automatic per-segment library provider.
2. Fake provider behavior remains available for tests/development.
3. Existing historical annotations are preserved and not migrated or deleted.
4. Hybrid Recall remains the candidate generator. Deep pass receives at most the requested Top-K candidates; default Top-K is 12, matching current `PlannerSettings.top_k`.
5. Each candidate is analyzed from three representative frames at 20/50/80 percent using the existing `FrameExtractor`.
6. Deep pass reuses the existing `QwenVideoUnderstandingProvider` and formal Bailian configuration only: `CLIPATLAS_BAILIAN_API_KEY` + `CLIPATLAS_BAILIAN_BASE_URL`.
7. Retrieval query, ASR text, OCR text, and source scores may be provided as retrieval context, but the provider prompt must explicitly treat them as non-visual context and must not copy them into visual facts unless visible in the frames.
8. Deep-pass results are in-memory in P0-7. No cache table or revision system is added.
9. RoughCut keeps its existing planner/scoring algorithm. Its search-hit type boundary is widened only enough to accept both old `SemanticSearchHit` and new deep-pass hits.
10. Deep-pass candidate identity is deterministic for `(video_id,start_ms,end_ms)` so reuse/continuity bookkeeping is stable within and across repeated planning calls. It is not a foreign key to `catalog_segments`.

## Data flow

```text
query / narration beat
    |
    v
HybridSearchService
visual + ASR + OCR
    |
    v
Top-K (default 12)
    |
    v
DeepPassService
    |
    +--> existing FrameExtractor -> 20/50/80% frames
    |
    +--> existing QwenVideoUnderstandingProvider (qwen3.8-flash)
    |
    v
DeepPassHit
hybrid score + deep SemanticAnnotation + provenance
    |
    v
existing RoughCutPlanner / CandidateScorer
    |
    v
OTIO / Jianying
```

## Library provider gate

The current `_select_library_provider()` auto-selects `qwen` when it is registered. That violates the Top-K-only architecture because `SequentialLibraryWorker._analyze_and_index_segments()` then calls qwen for every prepared segment.

P0-7 changes selection policy:

- `qwen` is never selected for library-wide segment analysis.
- `fake` may still be selected for tests/development.
- An explicit legacy `CLIPATLAS_LIBRARY_PROVIDER=qwen` does not re-enable whole-library qwen analysis and does not silently fall back to `fake`; it resolves to no library deep provider.

The Qwen provider may remain registered for other runtime uses; the deep-pass builder uses formal Bailian configuration directly to avoid third-party legacy key routing.

## DeepPassService

New file: `clipatlas/retrieval/deep_pass.py`.

Responsibilities:

- call Hybrid Recall with the requested limit;
- convert each merged candidate to a deterministic candidate UUID;
- resolve local `file://` source URI to a local path;
- extract representative frames with existing `FrameExtractor` under the existing library cache root;
- call existing `QwenVideoUnderstandingProvider.analyze_segment()` using `analysis_scope="top_k_deep_pass"`;
- return `DeepPassHit` carrying source range, hybrid score/provenance, provider/model, and `SemanticAnnotation`;
- delete successful temporary deep-pass frame files/directories after the provider has consumed them;
- propagate provider/frame failures rather than writing a second retry/checkpoint system.

P0-7 remains sequential per candidate. Concurrency is deferred until black-box latency/rate-limit evidence justifies it.

## Qwen prompt extension

The existing structured schema remains unchanged.

For `analysis_scope="top_k_deep_pass"`, append retrieval context to the text prompt:

- user query;
- ASR snippets;
- OCR snippets;
- source names/scores.

The prompt must label these as retrieval evidence, not visual truth. All returned `characters/actions/scene/emotions/objects/ocr/shot_type/camera_motion` remain visually grounded.

## RoughCut compatibility

Do not make `DeepPassService` manufacture `SemanticSearchHit` embedding metadata.

Instead introduce a structural `RoughCutSearchHit` Protocol containing only fields RoughCut actually consumes:

- `segment_id`
- `video_id`
- `source_uri`
- `source_start_ms`
- `source_end_ms`
- `score`
- `annotation`

`SemanticSearchHit` already satisfies this shape. `DeepPassHit` will also satisfy it. `SegmentSearch.search()` returns a `Sequence[RoughCutSearchHit]`, allowing both implementations without rewriting planner/scorer logic or database schemas.

## Runtime wiring

- Build Hybrid Recall as already implemented in P0-6.
- Build deep pass only when formal Bailian key/base URL are present.
- Attach `app.state.deep_pass_search_service` for internal RoughCut use.
- RoughCut uses deep-pass search when available; otherwise it keeps the existing semantic search fallback so existing installations are not hard-disabled.
- Do not expose a public `/api/v1/search/deep` endpoint in P0-7. Hybrid remains the public retrieval surface; deep pass is an internal candidate-refinement stage.

## Anti-overengineering constraints

Do not add:

- deep-pass SQLite tables;
- query hash/cache invalidation;
- qwen3-vl-rerank;
- extra Top-K environment variables;
- batch/concurrent deep pass;
- a new frame extraction implementation;
- a new Qwen deep provider class;
- OSS upload;
- background jobs/queues;
- public deep-search API;
- changes to ASR/OCR/video embedding persistence;
- changes to TTS/OTIO/Jianying.

## Verification requirements

Targeted tests must prove:

- qwen is not selectable as a whole-library provider;
- explicit legacy qwen does not fall back to fake;
- fake library-provider behavior remains intact when selected normally;
- Hybrid search receives exactly the requested Top-K limit;
- one candidate causes exactly three representative-frame extraction timestamps when duration permits;
- Qwen request receives `top_k_deep_pass` context and retrieval context is clearly non-visual;
- deterministic candidate identity is stable;
- temp frames are cleaned after success;
- DeepPassHit satisfies the RoughCut search shape;
- RoughCut uses deep pass when configured and old semantic search fallback when it is not;
- existing `/search/segments` and `/search/hybrid` behavior remains unchanged;
- `/api/v1/search/deep` is not publicly exposed.

Whole-repository Ruff/Mypy/Pytest/frontend verification is still required before any merge to the official active branch. If GitHub Actions executes zero steps, record infrastructure blockage rather than modifying production code to chase it.

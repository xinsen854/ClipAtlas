# Retrieval Intent Builder Design

Date: 2026-09-05
Branch: feat/bailian-index-ui-p0-8
Status: Design approved in chat; implementation not started

## 1. Goal

ClipAtlas is a second-creation rough-cut system. The retrieval layer must find footage that can visually express a narration/script beat, not merely footage containing the same words.

Current flow:

```text
Narration Beat
→ beat.query_text (raw narration)
→ Hybrid Recall (Visual + ASR + OCR)
→ Top-K qwen3.8 DeepPass
→ RoughCut
```

Problem: abstract narration can be semantically valid for editing while having weak literal overlap with observable footage. For example, a sentence about a product becoming a market leader may need footage of a formal launch, public presentation, testing, expert/media attention, or product hero shots. The system should derive those observable retrieval intents without hard-coding domain keywords.

The goal is to add one small query-expansion boundary before the existing search chain:

```text
Narration Beat
→ Retrieval Intent Builder
→ 1..N retrieval expressions
→ existing Hybrid Recall
→ existing Top-K qwen3.8 DeepPass
→ existing RoughCut
```

## 2. Non-goals

This change MUST NOT create a second indexing system.

Do not add:

- a new footage-semantic database;
- a new embedding index;
- persisted `editorial_semantics` for every video chunk;
- a new queue/checkpoint/retry system;
- domain-specific keyword maps such as `if 越野 then 泥地/爬坡`;
- new Hybrid scoring weights;
- new DeepPass scoring logic;
- a second video-understanding provider;
- changes to ASR/OCR/Visual ingestion;
- changes to OTIO/Jianying;
- Batch Rule Pack UI or persistence in this phase.

The existing Visual/ASR/OCR/Hybrid/DeepPass/RoughCut chain remains authoritative.

## 3. Core abstraction: Retrieval Intent

A single model is sufficient for V0.1. Do not split this into separate persistent Editorial Semantics and Visual Grounding subsystems.

Suggested shape:

```python
class RetrievalIntent(BaseModel):
    source_text: str
    meaning: list[str]
    visual_queries: list[str]
    entities: list[str]
```

Semantics:

- `source_text`: exact narration beat text; never rewritten in place.
- `meaning`: concise statement(s) of what the audience should understand.
- `visual_queries`: observable footage descriptions that could express or support that meaning.
- `entities`: named entities or literal anchors worth preserving during retrieval.

`meaning` and `visual_queries` are ephemeral retrieval aids, not canonical script text and not persisted footage truth.

## 4. General reasoning rules

The builder prompt must describe a general transformation method, not current automotive examples.

Rules:

1. Preserve facts stated by the user; do not invent concrete facts not present in the source text.
2. Identify what the beat wants the audience to understand.
3. If the meaning is abstract, convert it into camera-observable events, states, environments, interactions, demonstrations, or public evidence.
4. Do not require visible text to match narration wording.
5. Allow visually equivalent expressions of the same editorial meaning.
6. Preserve named entities that materially narrow the search.
7. Produce only a small number of complementary, high-coverage visual queries.
8. Do not encode industry-specific mappings in Python code or static lookup tables.

The builder is model-driven. Tests may use generic examples from multiple domains, but examples must not become production rules.

## 5. Search composition

Do not replace `BeatBuilder.query_text` with AI-generated text. Keep the original beat text intact.

Introduce an intent-aware search wrapper at the existing `SegmentSearch` boundary.

Conceptual flow:

```text
RoughCutPlanner
  calls SegmentSearch.search(original beat text)
        ↓
IntentAwareSearch
  asks RetrievalIntentBuilder to derive intent
        ↓
  runs existing downstream search for:
    - the original source text
    - each visual query
        ↓
  merges/deduplicates candidates
        ↓
  returns normal RoughCutSearchHit-compatible results
```

This keeps RoughCutPlanner unchanged and avoids contaminating canonical narration text with retrieval-only text.

### Candidate merging

V0.1 should reuse existing hit identity and downstream score semantics where possible.

Requirements:

- duplicate hits from multiple query variants must not become duplicate candidate segments;
- do not invent a second ranking formula in the wrapper;
- use the best existing downstream score for an identical segment/range;
- preserve downstream provenance/annotation fields;
- final Top-K qwen3.8 DeepPass remains the semantic verification layer.

If the existing hit type makes lossless deduplication awkward, introduce the narrowest adapter necessary rather than changing Hybrid/RoughCut models broadly.

## 6. Failure behaviour

Retrieval intent generation is an enhancement, not a reason to make rough-cut unusable.

Required behaviour:

- blank query → preserve existing blank-query behaviour;
- builder unavailable/not configured → call the existing search with the original query;
- builder upstream failure → fail open to the original query for V0.1;
- invalid structured builder output → fail open to the original query;
- no useful visual queries → use the original query only.

Do not add retries, persistent failure state, or a DLQ for this layer in V0.1.

Reason: the existing retrieval path is already validated. Intent generation should improve recall, not introduce a new availability dependency.

## 7. Provider boundary

Do not turn `QwenVideoUnderstandingProvider` into a general-purpose LLM service.

Preferred structure:

- reuse existing Bailian configuration;
- reuse existing HTTP/auth/structured-output infrastructure if it can be shared cleanly;
- keep retrieval-intent prompt/model separate from video-understanding prompt/model;
- do not duplicate an entire independent HTTP stack if a narrow shared transport can be extracted safely.

If no clean reusable transport exists without broad refactoring, a small dedicated text-structured provider is preferable to widening the video provider's responsibilities.

The implementation plan must choose the least invasive option after inspecting current provider code.

## 8. Batch Rule Pack future seam

Batch Rule Pack is deliberately not implemented in this phase.

Future rules such as:

- pronunciation overrides;
- speech suppression;
- speech replacement;
- subtitle replacement;
- entity aliases;
- semantic hints;

will be applied by channel. For retrieval, only `entity_alias` and `semantic_hint` should eventually be supplied as optional context to the Retrieval Intent Builder.

Do not pre-build rule persistence, approval UI, versioning, or TTS transformation hooks now.

The only requirement for V0.1 is that the builder API can later accept optional context without forcing a redesign.

## 9. Suggested implementation footprint

Expected production scope should remain small, approximately:

```text
clipatlas/retrieval/intent.py          # RetrievalIntent model + builder protocol/service
clipatlas/retrieval/intent_search.py   # thin SegmentSearch wrapper, if separation is useful
clipatlas/app_state.py                 # runtime wiring
```

Exact files may vary after implementation planning. Avoid touching RoughCutPlanner if a wrapper can satisfy the existing `SegmentSearch` protocol.

No database migrations.

## 10. Testing strategy

Use TDD.

Minimum behaviour tests:

1. Generic abstract statement produces observable visual queries.
2. Literal/source text is retained and still searched.
3. No domain-specific hard-coded mapping is needed for automotive, medical, tourism, technology, or other examples.
4. Duplicate candidates returned from multiple query variants are deduplicated.
5. Best existing downstream score is retained for duplicate candidate segments.
6. Builder failure falls back to original-query search.
7. Builder unavailable falls back to original-query search.
8. Invalid/empty intent falls back to original-query search.
9. RoughCutPlanner can consume the wrapper through the existing `SegmentSearch` contract without planner/scorer changes.
10. Existing Hybrid, DeepPass, RoughCut tests remain unchanged unless a strictly necessary fixture wiring change is required.

Real black-box acceptance should use second-creation-style narration whose visual meaning differs from its literal wording, not only exact OCR/ASR keyword queries.

## 11. Acceptance criteria

The change is accepted only if all are true:

- raw narration remains canonical and unmodified;
- retrieval intent is ephemeral and only affects search queries;
- abstract narration can produce observable visual search expressions;
- existing Hybrid/DeepPass/RoughCut architecture remains in place;
- no new persistent index/state is created;
- no current automotive terms are hard-coded;
- fallback to current search works if intent generation fails;
- duplicate query variants do not duplicate candidate footage;
- no new scoring formula is introduced merely to support intent expansion;
- later Batch Rule Pack context can be added without replacing this API.

## 12. Over-engineering guardrails

Before merge, reverse-audit the implementation against these questions:

1. Could the same result be achieved by fewer classes/files?
2. Did any code duplicate Hybrid, DeepPass, or provider responsibilities?
3. Did any current test/example leak into production as a domain rule?
4. Was any new persistence added without evidence it is needed?
5. Did the implementation alter RoughCut scoring or timeline behaviour?
6. Does the intent layer fail open to the already-proven retrieval path?
7. Is every new production abstraction necessary for the stated retrieval-intent boundary?

If the answer reveals duplicate responsibilities or speculative infrastructure, remove it before proceeding.

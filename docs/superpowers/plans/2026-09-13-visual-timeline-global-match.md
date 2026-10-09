# Visual Timeline Global Match Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the local video library into a reusable Chinese-first visual timeline map and use it to produce sentence-stable, evidence-aligned, low-duplication rough cuts with explicit fallback and optional API reranking.

**Architecture:** Ingest produces three stable semantic levels: Event (atomic timed evidence), Span (continuous semantic editing window), and Sequence (ordered process). Script analysis uses the same subject/action/scene/environment/object/configuration/quantity/relation/state vocabulary. Retrieval stays local and wide; hard evidence/media admission remains deterministic; an optional one-shot API reranker may reorder only already-legal candidates; final selection is global and deduplicated before clips are materialized.

**Tech Stack:** Python 3.12, Pydantic v2, FastAPI, SQLite, httpx, pytest.

**Spec:** User-approved ClipAtlas visual timeline + script matching requirements, 2026-09-13.

## Global Constraints

- Prefer one continuous shot per complete sentence; commas/periods may define boundaries, but do not fragment within a sentence unless the source window cannot cover it or independent S proofs require it.
- The spoken S anchor should overlap the strongest local evidence range whenever that evidence exists.
- No overlapping source range may repeat inside one output video.
- Batch reuse is avoided for the next 3–5 outputs when alternatives exist; scarce S DIRECT evidence may be reused after controlled degradation.
- Generic/b-roll is explicit, clean local footage used only as filler after exact/related candidates.
- Fallback ladder is explicit: exact → related → generic → source → reuse.
- Director/API failure, low match score, short footage, or reuse cooldown are quality degradations, not corruption.
- Only missing/unreadable source, illegal ranges, database corruption, or no readable legal material may block output.
- Title cards, PPT, technical charts, dense subtitles and mismatched black-text cards never bypass media admission through generic/source/reuse.
- All semantic prose stored for ingest and script analysis is Simplified Chinese; OCR/model/brand tokens are preserved as seen. Search uses Chinese canonical concepts plus English/acronym aliases where useful.
- API reranking cannot invent candidates, cannot upgrade REJECT/SUPPORT to DIRECT, and cannot bypass evidence/media rules.

---

### Task 1: Shared visual-language contract

**Files:**
- Modify: `clipatlas/domain/visual_protocol.py`
- Modify: `clipatlas/domain/evidence.py`
- Test: `tests/domain/test_visual_protocol.py`

**Interfaces:**
- Produces canonical searchable concept fields and bilingual alias text for both timeline events and script requirements.

- [ ] Add failing tests proving Chinese canonical values remain authoritative while English/acronym aliases are optional search expansions.
- [ ] Implement canonical search text helpers without changing evidence truth semantics.
- [ ] Run focused tests.

### Task 2: Stable Event → Span → Sequence timeline

**Files:**
- Modify: `clipatlas/catalog/timeline.py`
- Modify: `clipatlas/domain/models.py`
- Modify: `clipatlas/catalog/store.py`
- Test: `tests/catalog/test_timeline_protocol.py`
- Test: `tests/catalog/test_semantic_spans.py`

**Interfaces:**
- Produces long, continuous sequence windows while preserving timed atomic events and semantic anchor ranges.

- [ ] Add failing tests for a 40s same-speaker sequence with OCR changes remaining one sequence.
- [ ] Add failing tests for subject/scene/source-cut changes creating boundaries.
- [ ] Implement content-driven grouping; do not use fixed 5/10/15s semantic boundaries.
- [ ] Preserve timed OCR/event evidence without forcing sequence fragmentation.

### Task 3: Chinese-first script analysis using the same schema

**Files:**
- Modify: `clipatlas/director/analyzer.py`
- Modify: `clipatlas/director/requirements.py`
- Modify: `clipatlas/director/contract.py`
- Test: `tests/director/test_director.py`
- Test: `tests/director/test_claim_contract.py`

**Interfaces:**
- Produces `ScriptVisualRequirement` + typed claims aligned to subject/action/scene/environment/object/configuration/quantity/relation/state and exact source quote/anchor phrase.

- [ ] Add tests for Chinese-only semantic values and exact source quote preservation.
- [ ] Require whole-script one-shot analysis and sentence-level visual requirements.
- [ ] Keep local parser only as fallback.

### Task 4: Candidate API reranker with hard local guardrails

**Files:**
- Create: `clipatlas/director/reranker.py`
- Modify: `clipatlas/app_state.py`
- Test: `tests/director/test_reranker.py`

**Interfaces:**
- `CandidateReranker.rank(requirements, candidates) -> ranked candidate ids`.
- Consumes only candidates already admitted by local evidence/media policy.

- [ ] Add tests proving reranker cannot invent candidate ids.
- [ ] Add tests proving REJECT candidates are never submitted and SUPPORT is never promoted to DIRECT.
- [ ] Implement one API request for the whole candidate snapshot with deterministic fallback on API failure.

### Task 5: Sentence-stable candidate preparation and global assignment

**Files:**
- Modify: `clipatlas/roughcut/candidate_matrix.py`
- Create: `clipatlas/roughcut/global_assignment.py`
- Modify: `clipatlas/roughcut/planner.py`
- Test: `tests/roughcut/test_candidate_matrix.py`
- Test: `tests/roughcut/test_global_assignment.py`
- Test: `tests/roughcut/test_roughcut_planner.py`

**Interfaces:**
- Prepare all legal candidates before selection.
- Reserve scarce S DIRECT evidence first.
- Prefer one clip per complete sentence and align S anchor ranges to narration timing.

- [ ] Add tests where greedy selection is worse than global assignment.
- [ ] Add tests where one 10s continuous candidate beats three short candidates for one sentence.
- [ ] Add tests for exact S evidence selection even when a related candidate has higher vector similarity.
- [ ] Materialize clips only after assignment.

### Task 6: Hard dedup, batch cooldown, generic filler

**Files:**
- Modify: `clipatlas/roughcut/models.py`
- Modify: `clipatlas/roughcut/batch_assignment.py`
- Modify: `clipatlas/roughcut/planner.py`
- Modify: `clipatlas/retrieval/local_rough_cut.py`
- Test: `tests/roughcut/test_local_dedup.py`
- Test: `tests/roughcut/test_batch_reuse.py`

**Interfaces:**
- No same-source overlap inside one output.
- Default batch cooldown 5, tunable down to 3 by settings.
- Generic is explicit clean b-roll and never a media-policy bypass.

- [ ] Add tests for no repeated source range in one video.
- [ ] Add tests for avoiding a used 80% candidate in favor of an unused 75% candidate within cooldown.
- [ ] Add tests allowing controlled reuse after cooldown or when no legal alternative exists.

### Task 7: Unified pollution admission and must-output fallback

**Files:**
- Modify: `clipatlas/retrieval/local_rough_cut.py`
- Modify: `clipatlas/roughcut/planner.py`
- Test: `tests/retrieval/test_local_rough_cut.py`
- Test: `tests/roughcut/test_roughcut_planner.py`

**Interfaces:**
- Single media-admission function is used by exact/related/generic/source/reuse.
- Fallback ladder is observable in `schedule_level` and warnings.

- [ ] Add tests that mismatched title cards/PPT/dense text never enter via fallback.
- [ ] Add tests that a matching black-text card is allowed only in sentence-end/tail context.
- [ ] Add tests that all-polluted libraries choose approved clean generic or explicit local review placeholder instead of silently admitting pollution.
- [ ] Add tests that low-quality matching still outputs a draft whenever legal readable footage exists.

### Task 8: Quality and audit trail

**Files:**
- Modify: `clipatlas/roughcut/quality.py`
- Test: `tests/roughcut/test_evidence_quality.py`

**Interfaces:**
- Record requirement → local candidates → optional API order → global selection → final source range → evidence retained.

- [ ] Add metrics for sentence one-shot ratio, repeated source, batch repeated source, generic/source/reuse ratio, pollution count, S anchor overlap, and reranker usage.
- [ ] Keep human accuracy fields separate from automatic evidence metrics.

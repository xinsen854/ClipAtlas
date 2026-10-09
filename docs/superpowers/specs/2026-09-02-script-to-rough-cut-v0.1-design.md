# ClipAtlas Script-to-Rough-Cut V0.1 Design

## Goal

Build the canonical automatic rough-cut planner that consumes the active narration timing plus semantic retrieval results and produces a deterministic, persisted `RoughCutPlan` with exact source ranges and exact destination timeline ranges.

This subproject is **C only** in the approved Script-Driven Rough-Cut architecture. OTIO and Jianying/剪映 export remain a separate D subproject.

## Inputs already owned by ClipAtlas

The planner must reuse the existing canonical data instead of inventing parallel copies:

- `NarrationStore.get_active_track(project_id)` selects the active timing authority.
- `NarrationStore.list_units(track_id)` provides narration text and unit timing.
- `SemanticSearchService.search(query, limit, video_ids)` returns exact canonical footage ranges plus effective human-authoritative semantic annotations.
- `SemanticSearchHit.source_start_ms/source_end_ms` remain the hard source bounds.

The planner must never depend on provider-native speech objects, embedding payloads, or Jianying-specific structures.

## Global constraints

1. Real narration timing is authoritative whenever an active real narration track exists.
2. V0.1 automatic rough cut requires timed narration units. `TRACK_ONLY` imported narration is rejected until an aligner has produced unit timing.
3. The visual timeline must cover `0..NarrationTrack.duration_ms` without gaps or overlaps.
4. A selected source range may be trimmed **inside** a canonical segment but may never extend outside `source_start_ms..source_end_ms`.
5. Retrieval must return Top-K candidates before selection. The first cosine hit is not automatically chosen.
6. Candidate selection must use deterministic multi-signal scoring and deterministic tie-breaking.
7. Reuse of the same segment is penalized but not absolutely forbidden; footage-scarce projects must still be able to produce a complete plan.
8. A generated plan is persisted independently of later OTIO/Jianying export.
9. Same canonical inputs + same planner settings must produce the same plan ordering and source choices.
10. V0.1 does not add learned rerankers, transitions, effects, speed ramps, optical-flow refinement, final rendering, or Jianying writing.

## 1. Canonical models

### `ScriptBeat`

One narration-owned semantic editing window.

Required fields:

- `id`
- `project_id`
- `narration_track_id`
- `sequence`
- `text`
- `timeline_start_ms`
- `timeline_end_ms`
- `target_duration_ms`
- `query_text`

`target_duration_ms == timeline_end_ms - timeline_start_ms`.

V0.1 query text is deterministic and defaults to the narration unit text. Later LLM beat decomposition may enrich it without changing the planner contract.

### `CandidateScore`

Persistable scoring explanation for one candidate:

- `segment_id`
- `semantic_score`
- `action_score`
- `scene_score`
- `emotion_score`
- `duration_fit_score`
- `quality_score`
- `continuity_bonus`
- `reuse_penalty`
- `total_score`

All positive component scores are normalized to `0..1`. Penalties/bonuses are bounded and deterministic.

### `RoughCutClip`

A selected source range placed on the destination timeline:

- `beat_id`
- `segment_id`
- `video_id`
- `source_uri`
- `source_in_ms`
- `source_out_ms`
- `timeline_in_ms`
- `timeline_out_ms`
- `score`
- `score_breakdown`
- `selection_reason`

Required invariant:

`source_out_ms - source_in_ms == timeline_out_ms - timeline_in_ms`.

### `RoughCutPlan`

- `id`
- `project_id`
- `narration_track_id`
- `narration_revision`
- `revision`
- `total_duration_ms`
- `settings`
- `beats[]`
- `clips[]`
- `created_at`

The plan must be independent of any NLE format.

## 2. Beat timing policy

`BeatBuilder` reads the active narration track and its ordered units.

### Exact/Aligned tracks

Each unit must have `start_ms/end_ms`.

The builder rejects:

- missing timing;
- negative timing;
- overlapping units;
- unit end beyond track duration;
- empty text.

### Silence ownership

To guarantee full visual coverage while preserving speech alignment:

- leading silence belongs to the first beat;
- trailing silence belongs to the last beat;
- an internal silence gap between adjacent units is split at its midpoint: first half belongs to the previous beat, second half to the next beat;
- already contiguous unit boundaries remain unchanged.

This produces contiguous beat windows covering exactly `0..track.duration_ms` without fabricating word timestamps.

`TRACK_ONLY` and `ESTIMATED` tracks are not accepted by the V0.1 automatic planner. Estimated-only planning can be added later behind an explicit non-authoritative mode.

## 3. Semantic query and lexical structure signals

V0.1 does not introduce another LLM dependency for beat parsing.

The semantic query is the narration beat text itself. The embedding search therefore provides the primary semantic match.

For structured reranking, ClipAtlas derives deterministic lexical features from both beat text and annotation fields:

- Latin/digit tokens are lowercased words;
- contiguous CJK text contributes individual characters and overlapping 2-character grams;
- punctuation and empty tokens are ignored.

The same feature extraction is applied separately to annotation:

- `actions`
- `scene`
- `emotions`

`action_score`, `scene_score`, and `emotion_score` are overlap coefficients between beat features and each structured field feature set.

This is intentionally simple and auditable. A learned/LLM reranker can replace these components later without changing `CandidateScore` or planner inputs.

## 4. Candidate scoring

Default V0.1 score:

```text
base =
  0.58 * semantic_score
+ 0.08 * action_score
+ 0.08 * scene_score
+ 0.06 * emotion_score
+ 0.12 * duration_fit_score
+ 0.05 * quality_score
+ continuity_bonus
- reuse_penalty
```

Where:

- `semantic_score` is clamped from cosine similarity to `0..1`;
- `duration_fit_score = min(candidate_duration, needed_duration) / max(candidate_duration, needed_duration)`;
- `quality_score` uses annotation confidence when available, with a small deterministic verified bonus capped at `1.0`;
- `continuity_bonus` is at most `0.03` when the candidate is from the same video as the previous selected clip and is temporally close but non-overlapping;
- `reuse_penalty = min(0.20, 0.08 * prior_use_count_for_segment)`.

Tie-breaking order:

1. higher `total_score`;
2. higher `semantic_score`;
3. lower prior segment-use count;
4. lexical UUID order.

Weights are explicit planner settings so future tuning does not change persisted historical plans.

## 5. Duration filling policy

For each beat, the planner requests Top-K candidates once and greedily fills the beat until its target duration is satisfied.

Selection rules:

1. Score all candidates using the current reuse counts and previous selected clip.
2. Choose the highest deterministic score.
3. Available candidate duration is `source_end_ms - source_start_ms`.
4. Use `min(remaining_beat_ms, available_candidate_ms)`.
5. Trim from the candidate segment start for the first use in V0.1.
6. If the beat remains unfilled, rescore remaining candidates and continue.
7. Prefer unused candidates; reused candidates remain eligible with penalty.
8. If no candidate has positive usable duration, fail the plan with a normalized planning error instead of generating invalid time.

A long candidate may fill an entire beat by an in-segment trim. Multiple short candidates may fill one beat.

Every selected clip is checked against source bounds before persistence.

## 6. Continuity and reuse

V0.1 continuity is deliberately conservative:

- no hidden scene/story inference;
- no automatic jump-cut repair;
- no invented chronological relation between unrelated source videos.

The only continuity signal is a small deterministic bonus for nearby, non-overlapping source ranges from the same source video.

Reuse policy is global per plan. The same segment becomes progressively less attractive each time it is selected, but remains available as a fallback.

## 7. Persistence

Create a dedicated `RoughCutStore` using SQLite JSON payload persistence, following existing `NarrationStore` conventions.

Tables:

- `rough_cut_plans`
- `active_rough_cut_plans`

Plans are immutable by identity. Historical revisions remain accessible.

Methods:

- `save_plan(plan)`
- `get_plan(plan_id)`
- `next_plan_revision(project_id)`
- `activate_plan(project_id, plan_id)`
- `get_active_plan(project_id)`

A new plan revision never deletes an older one.

## 8. Planner service

`RoughCutPlanner` consumes:

- `NarrationStore`
- `SegmentSearch` protocol compatible with `SemanticSearchService.search()`
- `RoughCutStore`
- `PlannerSettings`

Primary method:

```python
async def create_plan(
    project_id: UUID,
    *,
    top_k: int = 12,
    video_ids: list[UUID] | None = None,
) -> RoughCutPlan
```

Flow:

```text
active narration track
→ timed narration units
→ BeatBuilder
→ per-beat Top-K semantic search
→ deterministic structured reranking
→ duration filling
→ invariant validation
→ persist RoughCutPlan revision
→ activate new plan
```

The planner must reject missing semantic-search runtime instead of silently producing empty selections.

## 9. API and runtime

Add a replaceable rough-cut runtime and API.

Endpoints:

- `POST /api/v1/rough-cut/plans`
- `GET /api/v1/rough-cut/plans/active?project_id=...`
- `GET /api/v1/rough-cut/plans/{plan_id}`

Create request fields:

- `project_id`
- `top_k` default `12`, minimum `1`, maximum `100`
- optional `video_ids`

The API returns normalized `409`/`503`-class errors for missing/untimed narration or unavailable semantic retrieval through existing error handling patterns.

## 10. Acceptance criteria

Script-to-Rough-Cut V0.1 is complete when tests prove:

1. active timed narration becomes the only automatic beat clock;
2. `TRACK_ONLY` imported narration is rejected;
3. beat windows cover the entire narration duration contiguously;
4. each beat performs Top-K semantic retrieval;
5. candidate selection uses semantic + structured + duration + quality + continuity/reuse signals;
6. repeated footage is penalized deterministically;
7. one long segment can be trimmed inside canonical bounds;
8. several short segments can fill one narration beat;
9. no selected source range exceeds its canonical segment bounds;
10. clips cover `0..NarrationTrack.duration_ms` without destination gaps/overlaps;
11. the same inputs/settings produce deterministic clip selection;
12. plan revisions persist without deleting history;
13. API can create and retrieve the active plan;
14. Ruff, strict Mypy, Pytest, and CI pass.

## 11. Explicit non-goals

Not in C V0.1:

- OTIO serialization;
- Jianying/剪映 draft generation;
- captions/subtitles;
- transitions/effects/BGM;
- automatic speed changes;
- optical flow;
- learned reranking;
- LLM beat rewriting;
- final video rendering.

Those remain separate follow-up work, especially D: `RoughCutPlan → OTIO → Jianying Adapter`.

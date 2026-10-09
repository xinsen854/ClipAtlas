# ClipAtlas Auto Director / Story Skill v0.1 Design

## Goal

Add a new **Auto Director** production path for creators who already have recorded footage. The system must understand the project's existing indexed footage, apply a user-replaceable Story Skill, produce an editable evidence-backed edit outline, let the user choose how narration is handled, and then reuse the existing RoughCut → FineCut → Export chain.

This is a separate user workflow from the existing "script/narration first" workflow. It must not send Auto Director users back through the manual script import screen.

## Product flow

```text
Project footage already scanned/indexed
    ↓
Auto Director
    ↓
Load / replace Story Skill
    ↓
Read existing visual analysis + ASR + OCR + timeline facts
    ↓
Whole-project story understanding / editorial re-ordering
    ↓
Generate edit outline (剪纲) with source evidence
    ↓
User edits / reorders / deletes outline nodes
    ↓
User confirms outline
    ↓
Narration strategy
    ├─ Preserve original spoken audio
    └─ Rebuild narration with TTS (voice clone is a later sub-project)
    ↓
Create one authoritative narration/edit timing input
    ↓
Existing RoughCut
    ↓
Existing FineCut
    ↓
Existing Export
```

## Non-goals for v0.1

- No second RoughCut implementation.
- No second TimelineDocument or FineCut editing model.
- No second media database or semantic index.
- No re-analysis of videos that already have usable indexed results.
- No executable Python/JavaScript Story Skills.
- No hard-coded Douyin/Bilibili/YouTube rules in production code.
- No cloud rendering or publish system.
- No full Premiere/Jianying replacement editor.
- No direct MP4 renderer in this first implementation slice.
- No voice-enrollment implementation in the first implementation slice; the existing TTS provider capability remains reusable later.

## Relationship to the existing workflow

The existing workflow remains intact:

```text
User-authored script
→ narration / TTS
→ RoughCut
→ FineCut
→ OTIO / Jianying draft
```

The new Auto Director workflow is different at the top:

```text
Existing footage facts
→ Story Skill
→ Auto Director outline
→ narration/edit timing decision
→ existing RoughCut
→ existing FineCut
→ existing Export
```

The old workflow is only regression-tested during implementation. Auto Director does **not** ask the user to upload a script after the system has already generated an outline.

## Existing code to reuse

### Indexed media facts

Reuse the current project-scoped library/indexing data and stores:

- visual semantic annotations / segment timeline
- ASR (`ASRStore`)
- OCR (`OCRStore`)
- project-owned media scope from the existing retrieval/search layer

The Auto Director must fail closed if project ownership cannot be established; it must never fall back to cross-project media.

### Existing Director infrastructure

Reuse the existing OpenAI-compatible API configuration and cache patterns, but do not overload the existing final-script `DirectorAnalyzer` contract with a second incompatible response schema.

The current `DirectorAnalyzer` remains responsible for analysing a final narration script for RoughCut visual matching. Auto Director adds a separate story-outline analyzer under the same `clipatlas.director` package with a focused contract.

### Existing RoughCut

The current `RoughCutPlanner` remains authoritative for shot retrieval, scheduling and creation of `RoughCutPlan`. Auto Director must adapt its confirmed result into the inputs RoughCut already consumes; it must not create a parallel planner.

### Existing FineCut and Export

FineCut remains the canonical editable timeline after RoughCut. Existing OTIO and Jianying export remain unchanged in v0.1.

Current export capabilities are draft-oriented, not direct MP4 rendering. Direct final-MP4 rendering is a separate later phase.

## Story Skill

### Purpose

A Story Skill tells Auto Director **how to tell the story**, not what happened in the footage.

Examples of rule categories:

- hook strategy
- ordering strategy
- reveal timing
- reversal / payoff strategy
- pacing
- desired duration
- original-speech cleanup policy
- ending strategy

### Input formats

v0.1 accepts text-only files:

- `.md`
- `.txt`
- `.json`
- `.yaml` / `.yml`

The backend reads the file as inert text/configuration. It never executes code from a Story Skill.

### Validation

A Story Skill must have non-empty content and a bounded file size. Invalid or unreadable files are rejected before any API call.

The system records a hash/revision of the exact Story Skill content used to produce an outline.

## Evidence-first story outline

Auto Director may reorder facts for narrative effect, but it must not invent facts that are unsupported by the indexed footage.

Each outline node contains at minimum:

- stable node id
- order
- title / editorial purpose
- concise narration/content summary
- role (`hook`, `setup`, `development`, `reversal`, `payoff`, `ending`, or `other`)
- source evidence references
- estimated duration

Each evidence reference contains enough source identity to recover the original footage:

- `video_id`
- source segment/timeline identity when available
- `start_ms`
- `end_ms`
- short evidence text / transcript excerpt when available

The UI may keep the evidence collapsed, but the backend contract must preserve it.

## Story analysis input

The story analyzer receives a compact project evidence packet built only from existing indexed data. It must not upload full source videos again simply to generate the outline.

The packet may contain:

- source video identity and duration
- time-bounded semantic descriptions
- ASR transcript segments with timestamps
- OCR observations with timestamps
- scene/event summaries already produced during ingest

The packet is ordered chronologically before being sent to the model. The Story Skill is provided separately and clearly labelled as editorial rules.

## Story analysis output

The analyzer returns structured JSON only. At minimum:

- project summary
- hook rationale
- ordered outline nodes
- evidence references per node
- estimated target duration
- warnings when the requested Story Skill cannot be supported by evidence

If a Skill demands a twist, death, accident, claim or event that is not supported by the indexed evidence, the model must not fabricate it. It should instead return a warning and use the strongest supported structure.

## Outline persistence and editing

The generated outline is persisted separately from `RoughCutPlan` and `TimelineDocument`.

It is an upstream planning artifact, not a second editing timeline.

Users can:

- edit node text
- reorder nodes
- delete nodes
- re-run story analysis with the same or a different Story Skill
- confirm one outline revision

Confirmation freezes the exact outline revision used to start automatic editing.

## Narration strategy

After outline confirmation, Auto Director asks for a narration strategy.

### A. Preserve original spoken audio

Use the evidence-backed ASR/source ranges associated with the confirmed outline to construct the authoritative spoken sequence from original media audio.

Expected behaviour:

- reorder selected spoken ranges according to the outline
- remove clearly configured filler/long pauses only when timestamp evidence supports the operation
- retain source linkage for every spoken segment
- produce timing data that RoughCut can use as its narration/edit backbone

This requires a thin adapter into the existing narration model/store, not a second audio timeline model.

### B. Rebuild narration with TTS

Generate narration text from the confirmed outline, then use the existing TTS/NarrationService path to create the authoritative narration track.

For v0.1, the user selects an existing configured voice/profile. Automatic voice enrollment from source audio is intentionally deferred.

### Later: voice clone enrollment

The speech contracts and DashScope provider already expose `voice_clone` capability metadata, but source-audio → custom voice enrollment is not currently implemented. That will be a separate phase after the core Auto Director path is proven.

## Integration boundary with RoughCut

Auto Director must end by producing an authoritative narration/edit timing input that satisfies existing RoughCut invariants.

The RoughCut planner remains unchanged in responsibility:

- project media isolation
- beat construction
- Director final-script analysis used for visual matching
- semantic retrieval
- shot selection and scheduling
- `RoughCutPlan` persistence

Auto Director does not bypass these checks.

## UI

Add an independent left-navigation entry/page: **自动编导**.

The page does not replace `文案与旁白`.

Minimum v0.1 layout:

1. Current project / indexed-media readiness summary.
2. Story Skill drop/select area.
3. `分析故事` action.
4. Editable outline cards with drag/reorder, text edit and delete.
5. Evidence disclosure per outline node.
6. `确认剪纲` action.
7. Narration strategy selector:
   - 保留原始口播
   - 使用现有 TTS 重新生成旁白
8. `开始自动剪辑` action.
9. On success, navigate to the existing RoughCut/FineCut flow using the newly created plan.

## Error handling

The page/API must distinguish:

- project has no indexed media
- indexing is incomplete
- no usable ASR for original-speech mode
- Story Skill invalid
- story provider not configured
- provider authentication/rate-limit/request failure
- returned outline is invalid
- evidence reference cannot be resolved
- RoughCut cannot find usable visual media

Provider failures must not destroy the last valid outline revision.

## Data ownership and safety

- Every outline belongs to exactly one project.
- Evidence references must resolve inside that project's media scope.
- No cross-project fallback is permitted.
- Outline edits never mutate source semantic annotations.
- Auto Director never mutates `TimelineDocument` directly.
- Failed automatic editing must not overwrite the previously active RoughCut/FineCut state.

## Delivery phases

### Phase A — Story Skill + evidence-backed outline

- independent Auto Director page
- Story Skill upload/replacement
- current-project evidence packet
- one API story analysis
- editable/persisted outline revisions
- confirmation

This phase stops before creating a RoughCut plan.

### Phase B — Original speech → existing RoughCut

- build original-speech narration sequence from confirmed evidence/ASR ranges
- create compatible narration timing
- invoke existing RoughCut planner
- enter existing FineCut

### Phase C — Existing TTS narration mode

- derive narration text from confirmed outline
- use existing speech profile/TTS service
- invoke the same existing RoughCut path

### Phase D — Voice enrollment

- source speaker sample selection
- provider-specific voice enrollment
- resulting `voice_id` flows through the existing TTS path

### Phase E — Direct MP4 render

Add a separate final-render service after the Auto Director core is stable. It should consume the canonical edit timeline and provide `final.mp4` without replacing OTIO/Jianying draft export.

## Acceptance for Phase A

Phase A is complete only when all are true:

1. Existing `文案与旁白` flow still passes regression tests.
2. A new `自动编导` page exists and is project-scoped.
3. A user can load/replace a Story Skill without executing code.
4. The backend builds a story-analysis packet from already-indexed project data.
5. One story-analysis API call returns a structured outline.
6. Every accepted outline node carries resolvable project-owned source evidence.
7. The user can edit/reorder/delete outline nodes.
8. The user can confirm an outline revision.
9. Re-analysis or provider failure does not destroy the last confirmed/valid revision.
10. No RoughCut, FineCut, TimelineDocument or export contract is duplicated or modified merely to support Phase A.

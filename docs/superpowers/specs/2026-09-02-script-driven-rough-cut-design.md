# ClipAtlas Script-Driven Rough-Cut Architecture Design

## Goal

Extend ClipAtlas from a video understanding/catalog system into a script-driven rough-cut system that can:

1. index corrected semantic meaning for each exact video segment,
2. generate or ingest narration and use the real narration timing as the editing clock,
3. decompose a script into timed beats,
4. retrieve and rank appropriate source footage for each beat,
5. build a deterministic rough-cut timeline,
6. export the internal timeline through OpenTimelineIO (OTIO),
7. produce Jianying/剪映 drafts through a replaceable adapter.

The architecture must remain provider-neutral for video understanding, embeddings, speech/TTS, and editing export.

## Scope decomposition

This architecture is implemented as four independently testable subprojects.

### Subproject A — Semantic Retrieval V0.1

Purpose: turn persisted segment annotations into searchable footage units with exact source time ranges.

### Subproject B — Narration/TTS V0.1

Purpose: produce or ingest narration audio and make real audio timing the authoritative editing clock.

### Subproject C — Script-to-Rough-Cut V0.1

Purpose: align script beats to narration time, retrieve source footage, rank candidates, enforce continuity/reuse constraints, and generate a rough-cut plan.

### Subproject D — OTIO and Jianying Export V0.1

Purpose: convert ClipAtlas rough-cut plans to a stable internal OTIO timeline and then to Jianying/剪映 drafts via an adapter.

These subprojects must be implemented in the order A → B → C → D.

---

# 1. Global principles

## 1.1 ClipAtlas owns canonical data

Vendor identifiers must never become the canonical identity of videos, segments, annotations, speech tracks, beats, matches, or timeline clips.

Canonical entities remain ClipAtlas-owned UUIDs.

## 1.2 Exact edit boundaries are local-authoritative

PySceneDetect/FFmpeg-derived `VideoSegment.start_ms` and `VideoSegment.end_ms` remain the authoritative source range.

AI/provider timestamps are evidence only and must never silently replace exact local boundaries.

## 1.3 Human semantic corrections are retrieval-authoritative

Confirmed rule: **A**.

For each segment:

- AI annotations remain immutable historical evidence.
- Human annotations remain separate revisions.
- Effective retrieval semantics are:
  - newest applicable human annotation, if one exists;
  - otherwise newest usable AI annotation.
- A human correction immediately invalidates/replaces the effective embedding used for retrieval.
- Previous AI and embedding records remain persisted for audit/history; they are not overwritten.

## 1.4 Real narration duration is the editing clock

When narration audio exists, edit timing must follow the real audio duration and aligned sentence/beat timestamps.

The authoritative narration source is selected by the project's current narration mode:

- `TTS ON` → the generated TTS audio and its normalized timing are authoritative.
- `TTS OFF + imported narration` → the user-imported narration and its normalized timing are authoritative.
- `TTS OFF + no narration` → estimated script timing is permitted only as a temporary planning fallback.

Switching narration mode replaces the active timing authority for future plans but does not delete historical narration tracks.

Editing logic must never force a fixed visual duration from text length when real narration timing is available.

## 1.5 Rough cut and export are separate

ClipAtlas rough-cut logic must not write Jianying-specific structures directly.

Canonical path:

```text
RoughCutPlan
→ OpenTimelineIO
→ Jianying Adapter
→ Jianying draft
```

This preserves future Premiere/Resolve/FCP adapters without rewriting retrieval or planning logic.

---

# 2. Subproject A — Semantic Retrieval V0.1

## 2.1 Retrieval unit

One searchable unit corresponds to one canonical `VideoSegment` and must resolve to:

- `segment_id`
- `video_id`
- `source_uri`
- `source_start_ms`
- `source_end_ms`
- effective semantic text
- structured semantic fields
- embedding vector
- embedding provider/model
- embedding source annotation identity/revision
- similarity score at query time

The retrieval result must therefore be directly usable by the later rough-cut planner without another lookup to rediscover source timing.

## 2.2 Effective semantic text

The effective text is deterministic and built from the retrieval-authoritative annotation.

Recommended field order:

```text
description
characters
actions
scene
emotions
objects
OCR
shot type
camera motion
```

Empty fields are omitted.

The normalized text builder must be provider-independent.

## 2.3 Embedding contract

Add a provider-neutral embedding capability separate from `VideoUnderstandingProvider`.

Conceptual contract:

```text
EmbeddingProvider
- name
- model
- dimensions
- embed_documents(texts)
- embed_query(text)
```

The first implementation may use Qwen embedding APIs, but Catalog/Index/Search code must only depend on this contract.

## 2.4 Persistence

V0.1 stores embeddings in SQLite as serialized float vectors plus metadata.

Required identity fields:

- segment ID
- annotation ID/revision used to build the effective text
- embedding provider
- embedding model
- dimensions
- vector
- created timestamp
- active/effective marker

SQLite linear cosine search is acceptable for V0.1.

Migration path:

```text
SQLite linear cosine
→ pgvector
```

The public retrieval interface must not change when the storage backend changes.

## 2.5 Reindex behavior

Reindex when any of the following changes:

- effective annotation changes,
- human correction becomes newest effective annotation,
- embedding provider/model changes,
- embedding dimension changes,
- segment is rebuilt because the source fingerprint changed.

Do not re-embed unchanged segments.

## 2.6 Retrieval API result

A hit must expose at minimum:

```json
{
  "segment_id": "uuid",
  "video_id": "uuid",
  "source_uri": "file:///...",
  "source_start_ms": 83420,
  "source_end_ms": 89170,
  "score": 0.91,
  "effective_description": "..."
}
```

The result can additionally expose structured semantic fields for later reranking.

## 2.7 Acceptance criteria

Semantic Retrieval V0.1 is complete when:

1. an AI-only segment can be indexed and retrieved by semantic query,
2. a human correction immediately becomes the effective search meaning,
3. the previous AI annotation remains persisted,
4. unchanged segments are not re-embedded,
5. every search hit contains exact source in/out timestamps,
6. search storage can later be replaced with pgvector without changing planner-facing interfaces.

---

# 3. Subproject B — Narration/TTS V0.1

## 3.1 Narration modes

The project exposes a narration/TTS switch.

Supported modes:

```text
TTS ON
→ generate narration through a SpeechProvider

TTS OFF + imported narration
→ analyze existing narration

TTS OFF + no narration
→ use estimated timing only as a temporary planning fallback
```

## 3.2 Provider-neutral SpeechProvider

Speech providers may be cloud APIs, custom HTTP endpoints, or local services.

Examples of adapters that may be implemented independently:

- Alibaba/Qwen speech
- Doubao/Volcengine TTS
- OpenAI speech
- ElevenLabs
- CosyVoice local
- GPT-SoVITS local
- custom HTTP provider

The core system must not depend on provider-specific parameter names.

## 3.3 Speech capabilities

Each provider advertises supported controls so the UI can enable/disable parameters instead of inventing unsupported settings.

Capability examples:

- voice selection
- gender filtering
- age style
- language
- accent
- speed
- pitch
- volume
- emotion
- style
- voice cloning
- sentence timestamps
- word timestamps

## 3.4 SpeechProfile

Canonical voice configuration:

```text
SpeechProfile
- provider
- voice_id
- gender
- age_style
- language
- accent
- speed
- pitch
- volume
- emotion
- style
- random_seed
- randomize_voice
- locked
```

Unsupported fields remain unset and must not be sent to a provider.

## 3.5 Randomization behavior

Confirmed rule: **project-level randomization, then lock**.

The UI may expose:

- random voice
- random parameters
- random all
- preview
- replace voice
- favorite
- lock

Randomization must be constraint-aware.

Example: when the user has selected `female + young + warm + Chinese`, random voice only chooses from compatible voices.

Default behavior must never randomize a different voice for each sentence.

A project gets one randomized profile and keeps it until the user explicitly replaces/unlocks it.

## 3.6 NarrationTrack

Canonical generated/imported result:

```text
NarrationTrack
- id
- project_id
- audio_uri
- duration_ms
- provider
- voice_id
- profile_snapshot
- segments[]
  - text
  - start_ms
  - end_ms
- words[] (when available)
  - text
  - start_ms
  - end_ms
```

## 3.7 Timing alignment

If the TTS provider returns sentence/word timestamps, persist them directly after normalization.

If it returns only audio:

```text
generated audio
→ forced alignment / ASR alignment
→ sentence and optionally word timestamps
```

The rough-cut planner consumes normalized narration timing, not provider-native timestamp formats.

## 3.8 Acceptance criteria

Narration/TTS V0.1 is complete when:

1. TTS can be switched on/off,
2. a user can import narration instead of generating it,
3. voice/gender/speed and provider-supported controls are configurable,
4. constrained random voice/profile selection works and can be locked per project,
5. custom HTTP and local-provider adapters can implement the same contract,
6. real narration duration becomes authoritative,
7. sentence-level timing always exists before automatic rough-cut planning.

---

# 4. Subproject C — Script-to-Rough-Cut V0.1

## 4.1 ScriptBeat

The script is decomposed into semantic editing beats.

Each beat contains:

- `beat_id`
- source text
- narration start/end
- target duration
- semantic query text
- desired actions
- desired scene
- desired emotion
- optional characters/objects/OCR intent
- pacing intent

When narration exists, beat target duration is derived from aligned narration timestamps.

## 4.2 Candidate retrieval

For every beat:

```text
beat semantic query
→ embedding retrieval
→ Top-K candidate segments
→ structured reranking
```

Retrieval must not immediately choose the top cosine score.

## 4.3 Reranking signals

The planner must have room for these independent signals:

- `semantic_score`
- `action_score`
- `emotion_score`
- `duration_fit`
- `continuity_score`
- `quality_score`
- `diversity_penalty`
- `reuse_penalty`

V0.1 may use deterministic weighted scoring before introducing a learned reranker.

## 4.4 Duration fitting

The narration beat defines the destination timeline duration.

A beat may be filled by:

- one continuous source range,
- multiple source ranges from one video,
- multiple source ranges from different videos.

The planner may trim within a canonical segment but must never request a source range outside its exact segment bounds.

## 4.5 RoughCutPlan

Canonical planner output:

```text
RoughCutPlan
- project_id
- narration_track_id
- total_duration_ms
- clips[]
  - beat_id
  - segment_id
  - video_id
  - source_uri
  - source_in_ms
  - source_out_ms
  - timeline_in_ms
  - timeline_out_ms
  - match scores
  - selection reason/metadata
```

This object is independent of Jianying.

## 4.6 Acceptance criteria

Script-to-Rough-Cut V0.1 is complete when:

1. script beats are aligned to real narration timing,
2. each beat retrieves multiple candidate segments,
3. candidate selection considers more than semantic similarity,
4. repeated footage can be penalized,
5. chosen clips obey exact source boundaries,
6. the total visual timeline follows narration duration,
7. the rough cut is deterministic for the same inputs/settings.

---

# 5. Subproject D — OTIO and Jianying Export V0.1

## 5.1 Canonical interchange

Convert `RoughCutPlan` into OpenTimelineIO.

OTIO stores:

- source references
- source in/out
- timeline placement
- track order
- narration audio placement
- later captions/transitions/effects when supported

## 5.2 Jianying adapter

The Jianying adapter consumes OTIO/ClipAtlas timeline data and writes the version-specific draft structure.

No retrieval, beat decomposition, scoring, or narration logic may exist inside the Jianying adapter.

## 5.3 Export failure isolation

A Jianying format/version incompatibility must fail only the export step.

The persisted `RoughCutPlan` and OTIO timeline remain valid and reusable.

## 5.4 Acceptance criteria

Export V0.1 is complete when:

1. a rough cut can be serialized to OTIO,
2. narration and selected video clips preserve millisecond timing,
3. a Jianying adapter produces an editable draft for the supported Jianying version,
4. export failure does not invalidate retrieval or rough-cut data,
5. a second NLE adapter could be added without changing planner interfaces.

---

# 6. End-to-end target flow

```text
Local video folders
→ ffprobe
→ PySceneDetect exact segments
→ representative frames
→ VideoUnderstandingProvider
→ AI semantic annotation
→ optional human correction
→ effective semantic authority
→ EmbeddingProvider
→ semantic index

Script
→ SpeechProfile / imported narration
→ TTS or narration ingest
→ real narration timing
→ sentence/word alignment
→ ScriptBeat decomposition
→ semantic Top-K retrieval
→ structured reranking
→ duration/continuity/reuse planning
→ RoughCutPlan
→ OTIO
→ Jianying Adapter
→ editable Jianying draft
```

# 7. Failure and resume rules

- Video understanding remains per-segment checkpointed.
- Embedding indexing is per-segment checkpointed.
- Human corrections trigger only the affected segment reindex.
- TTS generation persists audio/profile/timing before planning.
- Rough-cut generation persists its plan independently of export.
- Jianying export can be retried without rerunning AI analysis, embeddings, TTS, or matching.

# 8. Non-goals for the first pass

The first implementation sequence does not require:

- multi-user collaboration,
- cloud distributed job queues,
- learned reranking models,
- automatic transitions/effects/color grading,
- final render encoding,
- frame-accurate optical-flow cut refinement,
- direct dependence on one Jianying library implementation.

# 9. Implementation sequence

After this architecture is approved, implementation proceeds as four separate specs/plans:

1. `Semantic Retrieval V0.1`
2. `Narration/TTS V0.1`
3. `Script-to-Rough-Cut V0.1`
4. `OTIO + Jianying Export V0.1`

The first implementation plan must only cover Semantic Retrieval V0.1. TTS and editing remain architectural consumers until their own subproject specs are approved.

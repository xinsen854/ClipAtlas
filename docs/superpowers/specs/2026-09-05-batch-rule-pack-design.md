# Batch Rule Pack Design

## Goal
Add a project-scoped rule pack that lets users define per-job pronunciation, speech suppression/replacement, subtitle replacement, entity aliases, and semantic hints without modifying canonical source text or creating a second batch/project system.

## Scope boundary

- Existing `Project` is the batch boundary for V0.1. No new `Batch` entity.
- Canonical source text remains unchanged.
- Rules are project-scoped and revisioned.
- AI may propose candidate rules from natural-language instructions, but only confirmed rules become active.
- V0.1 does not add a generic DSL, permissions, workflow engine, second database, or global retry/cache system.
- V0.1 does not redesign subtitle export. It establishes a subtitle text projection API that future export/UI can consume.

## Rule types

Exactly six rule kinds are supported in V0.1:

1. `pronunciation` — replace matched text only for speech output.
2. `speech_suppress` — remove matched text only from speech output.
3. `speech_replace` — replace matched text only for speech output.
4. `subtitle_replace` — replace matched text only for subtitle output.
5. `entity_alias` — add alternate entity wording for retrieval without changing canonical text.
6. `semantic_hint` — provide project-specific semantic context to Retrieval Intent.

No automotive-specific or client-specific rules are built into code.

## Data model

`ProjectRulePack`

- `id: UUID`
- `project_id: UUID`
- `revision: int >= 1`
- `status: draft | active | archived`
- `source_text: str | None` — optional raw user instruction/document text used to derive candidate rules.
- `rules: list[ProjectRule]`
- `created_at`

`ProjectRule`

- `id: UUID`
- `kind: RuleKind`
- `match: str | None`
- `replacement: str | None`
- `hint: str | None`
- `enabled: bool`

Validation is type-specific and strict. Rules cannot silently become another kind.

## Persistence

Use the existing project database location and create only two small tables in a dedicated `ProjectRuleStore`:

- `project_rule_packs`
- `project_rules`

Only one active pack may exist per project. Activating a revision archives the previously active revision.

No changes are made to the `projects` table and no second database is introduced.

## Text projection

A pure `ProjectTextProjector` applies an active rule pack to canonical text and returns:

- `canonical_text` — exact input, unchanged.
- `speech_text` — pronunciation/speech suppression/speech replacement only.
- `subtitle_text` — subtitle replacement only.
- `retrieval_text` — canonical text plus entity aliases where relevant; canonical text is never discarded.
- `semantic_hints` — enabled semantic hints, separate from retrieval text.

Rules are applied deterministically in stored order. Exact literal matching only in V0.1. No regex engine and no fuzzy matcher.

## TTS integration

`NarrationService.create_tts_track()` continues to receive canonical script text. Before splitting/synthesis, it optionally projects each unit through the active project rule pack and sends only `speech_text` to the speech provider.

Canonical `NarrationUnit.text` remains canonical source text. The service must not overwrite it with speech-normalized text.

Checkpoint hashes remain based on canonical text plus the active rule pack revision so changing pronunciation rules cannot accidentally reuse old audio.

If no active rule pack exists, behavior is byte-for-byte equivalent to current TTS behavior.

## Retrieval integration

Retrieval Intent receives canonical source text plus `semantic_hints` and entity aliases as optional context. The existing Intent Builder remains responsible for general visual grounding. Batch rules never hard-code visual queries directly into retrieval code.

If no active rule pack exists, the current retrieval path is unchanged.

## Candidate-rule analysis

A future-facing `RulePackAnalyzer` interface accepts raw user instructions/document text and returns a draft pack containing only the six supported rule types.

For V0.1, the analyzer uses the existing formal Bailian configuration. Structured output is strictly validated. It cannot activate a pack.

Activation is a separate explicit store operation; this preserves the user confirmation boundary.

## UI/API boundary

V0.1 backend exposes enough capability for the frontend to later implement:

1. submit/paste raw rule instructions;
2. analyze into candidate rules;
3. edit/delete/enable candidate rules;
4. confirm and activate;
5. preview projected speech/subtitle/retrieval text.

File upload parsing is not implemented in the first backend slice. The API accepts text; frontend file ingestion can extract text later without changing rule semantics.

## Safety and anti-overengineering checks

- No new batch entity.
- No global rule registry.
- No rule inheritance across projects.
- No regex/fuzzy matching in V0.1.
- No mutation of canonical text.
- No new narration schema unless a demonstrated need appears during integration.
- No subtitle export rewrite.
- No automatic activation of AI-proposed rules.
- No client/domain-specific literals in production code.

## Acceptance criteria

- `泰钽700` can remain unchanged in canonical/subtitle/retrieval text while speech projects to `泰钽七百`.
- A configured phrase can remain in subtitle text but be removed from speech text.
- `TTS-7` can have a project-specific speech replacement without affecting later projects.
- A new project has no access to another project's rules.
- Revisions are preserved and only one revision is active.
- With no active rule pack, existing TTS and retrieval behavior is unchanged.

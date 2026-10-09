# Batch Rule Pack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add project-scoped, revisioned batch rules that preserve canonical text while producing independent speech, subtitle, retrieval, and semantic-hint projections.

**Architecture:** Reuse the existing `Project` as the batch boundary. Add a small `clipatlas.rules` package containing strict models, a SQLite store using the existing project DB, a pure projector, and a Bailian-backed candidate analyzer. Integrate projections at existing TTS and Retrieval Intent boundaries without changing canonical narration text or rebuilding indexes.

**Tech Stack:** Python 3.12, Pydantic v2, SQLite, httpx, FastAPI, existing Bailian configuration, existing React frontend.

**Spec:** `docs/superpowers/specs/2026-09-05-batch-rule-pack-design.md`

## Global Constraints

- Existing `Project` is the batch boundary; do not add a `Batch` model/table.
- Canonical source text must never be mutated by rules.
- Support exactly: `pronunciation`, `speech_suppress`, `speech_replace`, `subtitle_replace`, `entity_alias`, `semantic_hint`.
- AI-generated rules remain draft until explicit activation.
- No generic DSL, regex engine, fuzzy matcher, permissions layer, second DB, or global retry/cache system.
- No domain/client-specific production literals.
- With no active rule pack, current TTS and retrieval behavior must remain unchanged.

---

### Task 1: Strict rule models and pure text projection

**Files:**
- Create: `clipatlas/rules/__init__.py`
- Create: `clipatlas/rules/models.py`
- Create: `clipatlas/rules/projector.py`
- Test: `tests/rules/test_projector.py`

**Interfaces:**
- Produces: `RuleKind`, `RulePackStatus`, `ProjectRule`, `ProjectRulePack`, `ProjectedText`, `ProjectTextProjector.project(text, pack)`.

- [ ] Write failing tests proving canonical text stays exact, speech-only replacement/suppression does not affect subtitles, subtitle replacement does not affect speech, aliases affect retrieval only, semantic hints remain separate, and disabled rules do nothing.
- [ ] Run `python -m pytest tests/rules/test_projector.py -q` and confirm RED due missing module.
- [ ] Implement strict Pydantic models with type-specific validation and deterministic literal replacement in stored order.
- [ ] Run projector tests and confirm GREEN.
- [ ] Reverse-audit for regex/fuzzy/domain-specific logic and remove any unnecessary abstraction.

### Task 2: Project-scoped revision store

**Files:**
- Create: `clipatlas/rules/store.py`
- Test: `tests/rules/test_store.py`
- Modify: `clipatlas/app_state.py`

**Interfaces:**
- Produces: `ProjectRuleStore(db_path)`, `save_draft(pack)`, `get(pack_id)`, `list_project(project_id)`, `get_active(project_id)`, `activate(pack_id)`.

- [ ] Write failing tests for project isolation, revision preservation, exactly one active revision, activation archiving previous active revision, and deterministic rule order.
- [ ] Run store tests and confirm RED.
- [ ] Implement two tables in the existing `CLIPATLAS_PROJECT_DB`: `project_rule_packs` and `project_rules`.
- [ ] Add `build_project_rule_store()` next to `build_project_store()`; do not introduce another DB environment variable.
- [ ] Run store + project tests and confirm GREEN.

### Task 3: TTS speech projection without canonical-text mutation

**Files:**
- Modify: `clipatlas/speech/service.py`
- Modify: `clipatlas/app_state.py`
- Test: `tests/speech/test_rule_projection.py`

**Interfaces:**
- `NarrationService(..., rule_store: ProjectRuleStore | None = None, text_projector: ProjectTextProjector | None = None)`.

- [ ] Write failing tests showing a project rule can make canonical `泰钽700` synthesize as `泰钽七百` while saved `NarrationUnit.text` remains `泰钽700`; speech suppression removes speech-only phrases; another project is unaffected; no active pack preserves current behavior.
- [ ] Run tests and confirm RED.
- [ ] Project each canonical unit immediately before provider synthesis. Store canonical unit text, not speech text.
- [ ] Incorporate active pack revision into resumable TTS identity/checkpoint hashing so changed speech rules do not reuse old audio.
- [ ] Wire rule store/projector into `build_narration_runtime()`.
- [ ] Run existing speech suite plus new tests and confirm GREEN.

### Task 4: Retrieval context projection

**Files:**
- Modify: `clipatlas/retrieval/intent.py`
- Modify: `clipatlas/retrieval/intent_search.py`
- Modify: `clipatlas/app_state.py`
- Test: `tests/retrieval/test_rule_context.py`

**Interfaces:**
- Retrieval Intent keeps canonical `source_text` and accepts optional `semantic_hints` / entity aliases in context.

- [ ] Write failing tests that aliases and semantic hints are passed as context without replacing source text, and no active pack leaves current intent requests unchanged.
- [ ] Run tests and confirm RED.
- [ ] Add a thin project-aware context adapter before `RetrievalIntentBuilder`; do not alter Hybrid scoring or stored visual/ASR/OCR indexes.
- [ ] Run intent/hybrid/deep-pass regression suite and confirm GREEN.

### Task 5: Candidate rule analyzer

**Files:**
- Create: `clipatlas/rules/analyzer.py`
- Modify: `clipatlas/app_state.py`
- Test: `tests/rules/test_analyzer.py`

**Interfaces:**
- `RulePackAnalyzer.analyze(project_id, source_text) -> ProjectRulePack` returns `status=draft` only.
- `QwenRulePackAnalyzer` uses formal Bailian credentials/base URL.

- [ ] Write failing tests for natural-language instructions producing only the six supported kinds, preserving raw source text, refusing unsupported kinds, and never activating output.
- [ ] Run tests and confirm RED.
- [ ] Implement strict `json_schema` structured output with local Pydantic validation and no domain-specific prompt rules.
- [ ] Wire builder from `CLIPATLAS_BAILIAN_API_KEY` + `CLIPATLAS_BAILIAN_BASE_URL`; do not reuse third-party Qwen keys.
- [ ] Run analyzer tests and confirm GREEN.

### Task 6: Backend preview/confirm API

**Files:**
- Create: `clipatlas/api/rules.py` or follow the repository's existing router layout.
- Modify: `clipatlas/main.py`
- Test: `tests/api/test_project_rules.py`

**Interfaces:**
- `POST /api/v1/projects/{project_id}/rules/analyze`
- `GET /api/v1/projects/{project_id}/rules`
- `POST /api/v1/projects/{project_id}/rules/{pack_id}/activate`
- `POST /api/v1/projects/{project_id}/rules/preview`

- [ ] Write failing API tests for analyze→draft, preview projections, explicit activation, project isolation, and missing-project/pack errors.
- [ ] Run tests and confirm RED.
- [ ] Implement text-only analyze/preview/activate API. Do not add document-parser dependencies in V0.1.
- [ ] Run API tests and confirm GREEN.

### Task 7: Minimal frontend rule panel

**Files:**
- Modify only the existing project/settings/workbench frontend files that currently host narration/project controls; do not create a parallel application shell.
- Test: existing frontend test framework if present; otherwise build verification.

**Interfaces:**
- UI label: `本批附加规则`.
- User can paste instructions, analyze, inspect/edit/enable/delete candidate rules, preview speech/subtitle/retrieval projections, and explicitly confirm activation.

- [ ] Add the panel to the existing project workflow.
- [ ] Keep upload parsing out of V0.1; provide paste/input first and leave file-to-text as a later adapter.
- [ ] Verify the frontend build.
- [ ] Black-box test with pronunciation, speech suppression, and a second project proving isolation.

### Task 8: Final regression and anti-overengineering audit

**Files:** none expected beyond evidence-driven fixes.

- [ ] Run rule, project, speech, retrieval, roughcut, export regression suites.
- [ ] Verify no existing TTS/retrieval behavior changes when no active rule pack exists.
- [ ] Verify canonical text remains unchanged across TTS, retrieval, and export-facing models.
- [ ] Verify only `Project` scopes rules; no duplicate Batch concept exists.
- [ ] Verify production code contains no sample literals such as `泰钽700`, `央视`, `TTS-7`, `越野`.
- [ ] Record any observed real-material incompatibility before adding further compatibility logic.

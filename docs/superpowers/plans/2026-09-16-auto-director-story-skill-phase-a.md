# Auto Director Story Skill Phase A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first usable Auto Director slice: load a replaceable Story Skill, build a project-scoped evidence packet from already indexed footage, generate an evidence-backed editable outline, persist revisions, and confirm one outline.

**Architecture:** Add a focused story-outline analyzer under `clipatlas.director` without changing the existing final-script `DirectorAnalyzer`. Reuse `LibraryStore`, `CatalogStore`, `ASRStore`, `OCRStore`, existing Bailian/OpenAI-compatible configuration, and existing React shell. Persist outline revisions in a dedicated upstream planning store; do not create a second RoughCut or TimelineDocument.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLite, httpx, React, TypeScript, TanStack Query, Ant Design.

**Spec:** `docs/superpowers/specs/2026-09-16-auto-director-story-skill-design.md`

## Global Constraints

- Branch: `feat/auto-director-story-skill-v0.1`.
- Do not modify `TimelineDocument`, FineCut contracts, RoughCut responsibility, or existing export contracts for Phase A.
- Story Skill is inert text/config only; no executable Python/JavaScript plugins.
- Auto Director only reads project-owned indexed media and never falls back across projects.
- Auto Director does not ask the user to upload a script after generating an outline.
- Provider failure must not destroy previously persisted valid outlines.
- Phase A stops before narration creation or RoughCut creation.

---

### Task 1: Story outline domain and persistence

**Files:**
- Create: `clipatlas/director/story_models.py`
- Create: `clipatlas/director/story_store.py`
- Test: `tests/director/test_story_store.py`

**Interfaces:**
- Produces `StorySkill`, `StoryEvidenceItem`, `StoryEvidencePacket`, `StoryOutlineNode`, `StoryOutline`, `StoryOutlineEditNode`.
- Produces `StoryOutlineStore.save()`, `get()`, `list_project()`, `next_revision()`, `confirm()`.

- [ ] Write failing persistence/revision/confirmation tests.
- [ ] Run focused tests and confirm RED.
- [ ] Implement the minimal SQLite store.
- [ ] Run focused tests and confirm GREEN.
- [ ] Commit.

### Task 2: Project evidence packet

**Files:**
- Create: `clipatlas/director/story_evidence.py`
- Test: `tests/director/test_story_evidence.py`

**Interfaces:**
- Consumes project-owned `LibraryStore` items plus `CatalogStore`, `ASRStore`, and `OCRStore` records.
- Produces `StoryEvidencePacket build(project_id: UUID)` with deterministic evidence IDs and chronological facts.

- [ ] Write failing tests proving project isolation and visual/ASR/OCR aggregation.
- [ ] Run focused tests and confirm RED.
- [ ] Implement the builder using only existing indexed data.
- [ ] Run focused tests and confirm GREEN.
- [ ] Commit.

### Task 3: Story analyzer and service

**Files:**
- Create: `clipatlas/director/story_analyzer.py`
- Create: `clipatlas/director/story_service.py`
- Create: `clipatlas/director/story_errors.py`
- Test: `tests/director/test_story_service.py`

**Interfaces:**
- `StoryAnalyzer.analyze(skill, packet)` performs one OpenAI-compatible structured-output call.
- Model output references deterministic evidence IDs only; `StoryDirectorService` resolves them back to project-owned source evidence before persistence.
- `StoryDirectorService.edit()` only changes editable node fields and preserves source evidence.
- `StoryDirectorService.confirm()` confirms a persisted revision.

- [ ] Write failing tests for unsupported evidence IDs, revision editing, and provider failure preserving history.
- [ ] Run focused tests and confirm RED.
- [ ] Implement analyzer/service/error classes.
- [ ] Run focused tests and confirm GREEN.
- [ ] Commit.

### Task 4: API/runtime wiring

**Files:**
- Create: `clipatlas/api/routes/auto_director.py`
- Modify: `clipatlas/app_state.py`
- Modify: `clipatlas/main.py`
- Modify: `clipatlas/api/errors.py`
- Test: `tests/api/test_auto_director.py`

**Interfaces:**
- `POST /api/v1/auto-director/analyze`
- `GET /api/v1/projects/{project_id}/auto-director/outlines`
- `PUT /api/v1/auto-director/outlines/{outline_id}`
- `POST /api/v1/auto-director/outlines/{outline_id}/confirm`

- [ ] Write API RED tests for no service, invalid skill, analyze, edit, confirm, and project isolation.
- [ ] Run focused tests and confirm RED.
- [ ] Wire service into app state and routes.
- [ ] Run focused tests and confirm GREEN.
- [ ] Commit.

### Task 5: Auto Director frontend page

**Files:**
- Create: `frontend/src/api/autoDirector.ts`
- Create: `frontend/src/features/autoDirector/AutoDirectorPage.tsx`
- Create: `frontend/src/features/autoDirector/AutoDirectorPage.test.tsx`
- Modify: `frontend/src/app/router.tsx`
- Modify: `frontend/src/components/AppShell.tsx`

**Interfaces:**
- New route `/auto-director` and sidebar entry `自动编导`.
- Drag/select `.md/.txt/.json/.yaml/.yml` Story Skill.
- `分析故事` calls Phase A API.
- Outline nodes support text edit, up/down reorder, delete, save revision, and confirm.
- Evidence remains visible in collapsible detail and cannot be edited into new unsupported source references.

- [ ] Write frontend RED tests for navigation, skill loading, outline edit, and confirm.
- [ ] Run focused Vitest and confirm RED.
- [ ] Implement page/API wiring with existing component patterns.
- [ ] Run focused Vitest and confirm GREEN.
- [ ] Commit.

### Task 6: Phase A regression gate

**Files:** No production changes unless a real regression is demonstrated.

- [ ] Run `pytest tests/director tests/api/test_auto_director.py -q`.
- [ ] Run full backend `pytest -q`.
- [ ] Run frontend `npm run test:run -- --maxWorkers=1 --fileParallelism=false`.
- [ ] Run `npm run typecheck`.
- [ ] Run `npm run build`.
- [ ] Audit diff for no RoughCut/FineCut/TimelineDocument duplication.
- [ ] Stop Phase A; do not enter original-speech/TTS/MP4 work until Phase A is accepted.

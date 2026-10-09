# ClipAtlas Runtime UX Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make ClipAtlas easier to operate in real-machine workflows by fixing desktop scrolling, improving settings clarity/verification, and adding explicit single-item parse/reparse controls without changing core retrieval/edit/export behavior.

**Architecture:** Keep existing React/AntD/FastAPI/service boundaries. Visual changes stay in AppShell/theme/Settings components; provider connectivity tests are one-shot backend probes using current form values and never persist secrets; library per-item actions extend the existing LibraryStore/Worker/Supervisor rather than creating a new task system. Reparse reuses PreparedMediaCheckpointStore and preserves Human > AI effective-annotation precedence.

**Tech Stack:** React 19, TypeScript, Ant Design, TanStack Query, FastAPI, Pydantic, SQLite, httpx, pytest, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-04-runtime-ux-polish-design.md`

## Global Constraints

- Preserve exactly six primary navigation items.
- Keep provider/model/base URL configuration vendor-neutral.
- Test-connection secrets are request-only and must not be persisted or logged.
- Global pause stops automatic queue consumption but explicit single-item actions remain allowed.
- Reparse must preserve Human > AI precedence and annotation history.
- Do not modify RoughCut matching/scoring, OTIO/Jianying export core, or browser editing scope.
- Every behavior change follows RED -> minimal GREEN -> full Python/frontend CI -> diff review.

---

### Task 1: Fixed desktop shell and restrained warm theme

**Files:**
- Modify: `frontend/src/components/AppShell.tsx`
- Modify: `frontend/src/components/AppShell.test.tsx`
- Modify: `frontend/src/app/theme.ts`

**Interfaces:**
- Consumes: existing `AppShell`, AntD `Layout`/`Menu`, existing six `primaryItems`.
- Produces: fixed `Sider` viewport layout and right-only scrolling without changing routes.

- [ ] **Step 1: Write failing layout tests**

Add assertions that the sidebar exposes a stable test selector or style contract and the content area is the scrolling container. The test should verify all six nav labels remain present and that the shell does not add a seventh item.

Example target assertions:

```tsx
expect(screen.getByTestId('app-sidebar')).toHaveStyle({ position: 'fixed' })
expect(screen.getByTestId('app-content-scroll')).toHaveStyle({ overflow: 'auto' })
expect(screen.getAllByRole('menuitem')).toHaveLength(6)
```

- [ ] **Step 2: Run frontend test and confirm RED**

Run:

```bash
cd frontend
npm test -- --run src/components/AppShell.test.tsx
```

Expected: fail because `app-sidebar` / `app-content-scroll` fixed-scroll contract does not exist.

- [ ] **Step 3: Implement minimal fixed shell**

In `AppShell.tsx`:

```tsx
<Sider
  data-testid="app-sidebar"
  width={216}
  theme="light"
  style={{
    position: 'fixed',
    insetInlineStart: 0,
    top: 0,
    bottom: 0,
    height: '100vh',
    borderRight: '1px solid #eadfd6',
    background: '#fffdf9',
  }}
>
```

Offset the right layout by `marginInlineStart: 216`, set its height to `100vh`, and make the `Content` element the only vertical scrolling region with `data-testid="app-content-scroll"`, `overflow: 'auto'`, and `minHeight: 0`.

In `theme.ts`, add restrained tokens such as:

```ts
colorPrimary: '#d97706',
colorInfo: '#d97706',
colorBgLayout: '#f8f4ef',
colorText: '#26211d',
borderRadius: 10,
```

Do not override semantic success/error colors.

- [ ] **Step 4: Run frontend tests/typecheck/build**

```bash
cd frontend
npm test -- --run src/components/AppShell.test.tsx
npm run typecheck
npm run build
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/AppShell.tsx frontend/src/components/AppShell.test.tsx frontend/src/app/theme.ts
git commit -m "feat: 固定桌面侧栏并统一暖色主题"
```

---

### Task 2: Settings visual grouping, copy, connection tests, and optional model listing

**Files:**
- Modify: `frontend/src/features/settings/SettingsSection.tsx`
- Modify: `frontend/src/features/settings/SettingsPage.tsx`
- Modify: `frontend/src/features/settings/SettingsPage.test.tsx`
- Modify: `frontend/src/api/settings.ts`
- Modify: `clipatlas/api/routes/settings.py`
- Modify: `clipatlas/settings/models.py`
- Create: `clipatlas/settings/probe.py`
- Test: `tests/test_settings_api.py` (or the existing settings API test file if named differently)
- Test: `tests/test_settings_probe.py`

**Interfaces:**
- Consumes: current unsaved provider/base URL/model/key form values; existing httpx dependency; current settings route.
- Produces:
  - `POST /api/v1/settings/test-connection`
  - `POST /api/v1/settings/models`
  - one-shot request/response models that never persist secrets.

Define backend request types:

```python
ServiceKind = Literal["video", "embedding", "speech"]

class ServiceProbeRequest(BaseModel):
    service: ServiceKind
    provider: str
    api_key: str
    base_url: str
    model: str
    dimensions: int | None = Field(default=None, gt=0)

class ServiceProbeResponse(BaseModel):
    ok: bool
    code: Literal[
        "ok", "auth_failed", "forbidden", "not_found", "rate_limited",
        "timeout", "network_error", "model_unavailable", "upstream_error"
    ]
    message: str
    latency_ms: int | None = None

class ModelListResponse(BaseModel):
    models: list[str]
    supported: bool
```

- [ ] **Step 1: Write backend RED tests**

Tests must prove:

1. Probe request data is not written into SettingsStore.
2. OpenAI-compatible video/embedding probe handles 200, 401, 404, 429 and timeout distinctly.
3. Speech probe uses the configured speech endpoint/provider contract and reports configuration/auth failure without synthesizing a real long narration.
4. `/models` returns model IDs for an OpenAI-compatible `/models` response and returns `supported=false` for unsupported provider/protocol rather than rejecting manual entry.

Use `httpx.MockTransport` or injected `AsyncClient`; do not call real vendors in CI.

- [ ] **Step 2: Run backend RED**

```bash
pytest tests/test_settings_probe.py tests/test_settings_api.py -q
```

Expected: fail because probe/models endpoints and probe service do not exist.

- [ ] **Step 3: Implement minimal probe service**

Create `clipatlas/settings/probe.py` with a small service that:

- normalizes `base_url.rstrip('/')`;
- for OpenAI-compatible video uses a minimal `/chat/completions` request with a tiny text-only prompt when the model endpoint permits it, or a provider-specific minimal model availability request where existing adapters require it;
- for embedding uses a one-item `/embeddings` request with input `"ping"` and requested dimensions when supported;
- for speech uses a minimal short text `"测试"` request through the existing provider adapter or provider-specific endpoint contract, discarding returned audio;
- maps `httpx` response/transport failures to `ServiceProbeResponse` codes;
- never writes to SettingsStore and never logs the supplied key.

Implement model listing only for OpenAI-compatible providers by GETting `{base_url}/models`; otherwise return `supported=false` and an empty list.

- [ ] **Step 4: Wire settings routes**

Add async POST routes:

```python
@router.post('/test-connection', response_model=ServiceProbeResponse)
async def test_connection(payload: ServiceProbeRequest) -> ServiceProbeResponse: ...

@router.post('/models', response_model=ModelListResponse)
async def list_models(payload: ServiceProbeRequest) -> ModelListResponse: ...
```

Keep existing GET/PATCH behavior unchanged.

- [ ] **Step 5: Write frontend RED tests**

Tests must verify:

- Each of 视频理解 / 语义索引 / 语音 sections has `测试连接`.
- Current typed, unsaved key/base URL/model values are sent to the test API.
- A successful response renders a success status; auth/rate-limit/timeout render explicit messages.
- `获取模型` populates selectable model options when supported, but manual `<Input>` remains available on unsupported/failure.
- Embedding section contains Chinese explanation `语义向量模型（用于按意思搜索素材）`.
- Jianying helper copy distinguishes install directory, executable path, and user-data requirements.

- [ ] **Step 6: Implement Settings UI minimal GREEN**

Extend `SettingsSection` with a variant prop:

```ts
type SettingsSectionTone = 'video' | 'embedding' | 'speech' | 'jianying'
```

Map tones to subtle card backgrounds/borders. Keep child inputs white.

Add API helpers:

```ts
export function testServiceConnection(input: ServiceProbeRequest): Promise<ServiceProbeResponse>
export function fetchServiceModels(input: ServiceProbeRequest): Promise<ModelListResponse>
```

In `SettingsPage`, construct requests from current `form.getFieldsValue()` plus the in-memory secret fields, so unsaved values are tested. Never save as part of test/fetch actions.

Recommended helper copy is muted text only and must not become validation.

- [ ] **Step 7: Verify Task 2**

```bash
ruff check .
mypy clipatlas
pytest -q
cd frontend
npm test -- --run
npm run typecheck
npm run build
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add clipatlas/settings clipatlas/api/routes/settings.py tests frontend/src/api/settings.ts frontend/src/features/settings
git commit -m "feat: 增加服务连接测试并优化设置分区"
```

---

### Task 3: Explicit single-item parse and reparse backend semantics

**Files:**
- Modify: `clipatlas/library/store.py`
- Modify: `clipatlas/library/worker.py`
- Modify: `clipatlas/library/supervisor.py`
- Modify: `clipatlas/api/routes/library.py`
- Modify: `clipatlas/catalog/store.py` only if a focused query/helper is required for AI revision calculation
- Test: existing `tests/test_library_store.py`
- Test: existing `tests/test_library_worker.py`
- Test: existing `tests/test_library_supervisor.py`
- Test: existing `tests/test_library_api.py`

**Interfaces:**
- Consumes: `PreparedMediaCheckpointStore`, existing `SequentialLibraryWorker`, existing effective-annotation/embedding rules.
- Produces:
  - `POST /api/v1/library/items/{item_id}/parse`
  - `POST /api/v1/library/items/{item_id}/reparse`
  - worker method that explicitly processes a requested item without resuming automatic queue consumption.

Target worker interface:

```python
async def run_item(self, item_id: UUID, *, force_ai: bool = False) -> bool: ...
```

`run_once()` remains for automatic queue operation and delegates to the shared processing path.

- [ ] **Step 1: Write store/supervisor RED tests**

Cover:

- queued item can be explicitly claimed by ID;
- another state cannot be double-claimed while in-flight;
- completed/failed item can be placed into explicit reparse flow;
- explicit run while supervisor is paused does not change `paused`;
- no automatic second item runs after explicit item completion.

- [ ] **Step 2: Write worker RED tests for checkpoint reuse and force AI**

Prepare a completed item with a valid preparation checkpoint and historical AI annotation.

Assert on `run_item(item.id, force_ai=True)`:

- `processor.prepare()` is not called when checkpoint/catalog prepared video is valid;
- provider `analyze_segment()` is called even if historical AI annotation exists;
- new AI annotation is saved as a later revision rather than deleting history;
- indexer is called for every segment;
- if the effective annotation is Human, effective result remains Human after the AI revision is saved;
- missing checkpoint falls back to `processor.prepare()`.

- [ ] **Step 3: Run RED tests**

```bash
pytest tests/test_library_store.py tests/test_library_worker.py tests/test_library_supervisor.py tests/test_library_api.py -q
```

Expected: fail because explicit claim/run/reparse APIs do not exist and current worker skips existing provider AI annotations.

- [ ] **Step 4: Implement explicit item claim and shared worker path**

In `LibraryStore`, add an atomic claim-by-ID method using `BEGIN IMMEDIATE`; only allow expected source statuses and increment attempts once.

Do not expose arbitrary paths.

In `SequentialLibraryWorker`, refactor only enough to share processing logic:

```python
async def _process_claimed(self, item: LibraryItem, *, force_ai: bool) -> bool: ...
async def run_item(self, item_id: UUID, *, force_ai: bool = False) -> bool: ...
```

When `force_ai=True`, bypass `has_ai_annotation(...)` for AI generation, but keep effective-annotation selection unchanged. Assign AI revision as the next AI revision for that segment/provider/model history rather than replacing records.

After saving the AI result, call the existing semantic indexer. Since the indexer reads the effective annotation, Human > AI remains preserved.

- [ ] **Step 5: Add API endpoints**

`/parse` accepts only queued/waiting items and executes one requested item.

`/reparse` accepts completed/failed items and uses `force_ai=True`.

Both must require a configured video-understanding provider; respond with 409/503 according to existing API conventions when unavailable or the item state is invalid.

Do not call `supervisor.resume()` from either endpoint.

- [ ] **Step 6: Verify Task 3**

```bash
ruff check .
mypy clipatlas
pytest -q
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add clipatlas/library clipatlas/catalog clipatlas/api/routes/library.py tests
git commit -m "feat: 支持单条解析与安全重新解析"
```

---

### Task 4: Library terminology/actions and TTS guidance

**Files:**
- Modify: `frontend/src/utils/statusMaps.ts`
- Modify: `frontend/src/features/library/LibraryItemTable.tsx`
- Modify: `frontend/src/features/library/LibraryPage.tsx`
- Modify: `frontend/src/features/library/LibraryPage.test.tsx`
- Modify: `frontend/src/features/library/useLibraryActions.ts`
- Modify: `frontend/src/features/library/useLibraryActions.test.tsx`
- Modify: `frontend/src/api/library.ts`
- Modify: `frontend/src/features/narration/NarrationPage.tsx`
- Modify: `frontend/src/features/narration/NarrationPage.test.tsx`

**Interfaces:**
- Consumes: Task 3 `/parse` and `/reparse` endpoints; existing global pause/resume state.
- Produces: user-facing `解析` terminology and per-row controls.

- [ ] **Step 1: Write frontend RED tests**

Cover:

- labels render `解析状态 / 等待解析 / 解析中 / 解析完成 / 解析失败`;
- queued row shows `单条解析`;
- completed and failed rows show `重新解析`;
- in-flight row has no duplicate-start action;
- while global paused, clicking `单条解析` still calls only the item parse endpoint and does not call resume;
- after explicit item action, processing-state query still reports paused if it was paused;
- unavailable TTS warning includes a clear Settings route/action while human narration remains available.

- [ ] **Step 2: Run frontend RED**

```bash
cd frontend
npm test -- --run src/features/library/LibraryPage.test.tsx src/features/library/useLibraryActions.test.tsx src/features/narration/NarrationPage.test.tsx
```

Expected: fail on old `处理` copy and missing parse/reparse actions.

- [ ] **Step 3: Add API/action helpers**

In `frontend/src/api/library.ts`:

```ts
export function parseLibraryItem(itemId: string): Promise<{status: string}>
export function reparseLibraryItem(itemId: string): Promise<{status: string}>
```

Add TanStack mutations that invalidate library items/summary after completion but never mutate global processing pause state.

- [ ] **Step 4: Update table copy and action rules**

Use status-to-action mapping:

```ts
QUEUED -> 单条解析
COMPLETED -> 重新解析
FAILED -> 重新解析
PROBING/SCENE_DETECTION/FRAME_EXTRACTION -> no start button
```

Keep existing status filtering/data model; do not rename backend enums.

- [ ] **Step 5: Add TTS Settings guidance**

When no speech provider exists, include a React Router link/button to `/settings` labeled `去设置语音 API`; do not add API key fields to NarrationPage.

- [ ] **Step 6: Full final verification and scope review**

```bash
ruff check .
mypy clipatlas
pytest -q
cd frontend
npm test -- --run
npm run typecheck
npm run build
```

Then review the final diff against `main` and confirm:

- no RoughCut/OTIO/Jianying export-core changes;
- no provider lock-in;
- no persisted test secrets;
- no arbitrary path/command inputs added;
- Human > AI remains effective;
- explicit single-item parse does not unpause automatic processing.

- [ ] **Step 7: Commit**

```bash
git add frontend/src
 git commit -m "feat: 完成解析控制与实机操作体验收口"
```

# ClipAtlas Chinese Frontend V0.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first Chinese local Web workbench for ClipAtlas, consuming the existing and Stage-A product APIs to manage media, correct annotations, search semantically, prepare narration, generate/review rough cuts, and export/open Jianying drafts without implementing an editor timeline.

**Architecture:** Create an isolated `frontend/` React application. TanStack Query owns server state; Zustand stores only current-project and small UI preferences. Production `vite build` output is served by FastAPI as SPA static resources, while development uses Vite proxying `/api` and `/health` to FastAPI. The UI presents product-language Chinese labels and never reproduces backend semantic/ranking/timeline logic in the browser.

**Tech Stack:** React, TypeScript, Vite, React Router, TanStack Query, Zustand, Ant Design, Vitest, React Testing Library, npm; existing FastAPI/Python backend for static serving and launch command.

**Spec:** `docs/superpowers/specs/2026-09-03-chinese-frontend-v0.1-design.md`

**Backend prerequisite:** `docs/superpowers/plans/2026-09-03-frontend-contract.md` Stage A must be implemented and green before functional Stage-B pages are accepted.

## Global Constraints

- Chinese UI is the default; hide English implementation terms from normal users.
- Six primary navigation entries only: 工作台、素材库、素材搜索、文案与旁白、自动粗剪、设置.
- 当前项目 is global context, not a seventh primary page.
- No login/registration/permissions.
- No video player or video preview in V0.1.
- No editing timeline, multitrack editor, drag trim, transitions, subtitle editor, color grading, BGM, or SFX editor.
- Exact canonical timings may be shown as text but never as an editing timeline widget.
- Do not calculate semantic similarity, annotation precedence, narration timing, rough-cut scoring, source in/out, or export timing in the frontend. Display backend authority.
- Human annotation PATCH must invalidate and refetch affected Segment/search data.
- Real NarrationTrack duration is authoritative for rough-cut UI.
- API secrets are never displayed after save; blank secret fields are not submitted as clear operations.
- Use Ant Design components as primitives, but do not adopt a generic enterprise-admin template.
- No second server-state cache in Zustand.
- Frontend tests must run without backend/network by mocking the API boundary.
- `打开草稿目录` must send only the trusted `plan_id` to the backend system bridge; the browser must not send arbitrary filesystem paths.

---

## Frontend File Map

```text
frontend/
├─ index.html
├─ package.json
├─ package-lock.json
├─ tsconfig.json
├─ tsconfig.app.json
├─ tsconfig.node.json
├─ vite.config.ts
├─ vitest.config.ts
└─ src/
   ├─ main.tsx
   ├─ app/
   │  ├─ App.tsx
   │  ├─ router.tsx
   │  ├─ queryClient.ts
   │  └─ theme.ts
   ├─ api/
   │  ├─ client.ts
   │  ├─ errors.ts
   │  ├─ health.ts
   │  ├─ projects.ts
   │  ├─ library.ts
   │  ├─ search.ts
   │  ├─ speech.ts
   │  ├─ roughCut.ts
   │  ├─ exports.ts
   │  ├─ settings.ts
   │  └─ system.ts
   ├─ components/
   │  ├─ AppShell.tsx
   │  ├─ PageHeader.tsx
   │  ├─ EmptyState.tsx
   │  ├─ LoadingBlock.tsx
   │  ├─ ErrorBlock.tsx
   │  ├─ StatusTag.tsx
   │  └─ ProjectSwitcher.tsx
   ├─ features/
   │  ├─ projects/
   │  ├─ dashboard/
   │  ├─ library/
   │  ├─ annotation/
   │  ├─ search/
   │  ├─ narration/
   │  ├─ roughcut/
   │  ├─ export/
   │  └─ settings/
   ├─ stores/
   │  └─ useAppStore.ts
   ├─ utils/
   │  ├─ format.ts
   │  └─ statusMaps.ts
   └─ test/
      ├─ setup.ts
      ├─ render.tsx
      └─ fixtures.ts
```

Backend integration near the end:

- Create: `clipatlas/web.py` — static SPA mounting.
- Create: `clipatlas/cli.py` — one-command local launch + browser open.
- Modify: `clipatlas/main.py` — mount built frontend after API routers.
- Modify: `pyproject.toml` — console script.
- Modify: `README.md` — frontend development/build/start instructions.
- Test: `tests/api/test_frontend_static.py`
- Test: `tests/test_cli.py`

---

### Task 1: Scaffold frontend with test/build/typecheck gates

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/package-lock.json`
- Create: `frontend/index.html`
- Create: `frontend/tsconfig.json`
- Create: `frontend/tsconfig.app.json`
- Create: `frontend/tsconfig.node.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/vitest.config.ts`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/app/App.tsx`
- Create: `frontend/src/app/queryClient.ts`
- Create: `frontend/src/app/theme.ts`
- Create: `frontend/src/test/setup.ts`
- Create: `frontend/src/app/App.test.tsx`

**Interfaces:**

```json
{
  "dev": "vite",
  "build": "tsc -b && vite build",
  "test": "vitest",
  "test:run": "vitest run",
  "typecheck": "tsc -b --pretty false"
}
```

Production output: `frontend/dist`.

Dev API target: `http://127.0.0.1:8000`.

- [ ] **Step 1: Create npm project and install dependencies**

```bash
mkdir frontend
cd frontend
npm init -y
npm install react react-dom react-router-dom @tanstack/react-query zustand antd @ant-design/icons
npm install -D typescript vite @vitejs/plugin-react vitest jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event @types/react @types/react-dom
```

Commit generated `package-lock.json`; no CDN runtime dependencies.

- [ ] **Step 2: Set exact npm scripts**

Use the script object above.

- [ ] **Step 3: Configure Vite/Vitest**

`vite.config.ts`:

```ts
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
    },
  },
})
```

Vitest uses `jsdom` and `src/test/setup.ts` importing `@testing-library/jest-dom/vitest`.

- [ ] **Step 4: Write first failing render test**

```tsx
import { render, screen } from '@testing-library/react'
import { App } from './App'

test('renders ClipAtlas application name', () => {
  render(<App />)
  expect(screen.getByText('ClipAtlas')).toBeInTheDocument()
})
```

- [ ] **Step 5: Run RED**

```bash
npm run test:run -- src/app/App.test.tsx
```
Expected: FAIL until app/test setup exists.

- [ ] **Step 6: Implement minimal providers**

```tsx
<ConfigProvider locale={zhCN} theme={theme}>
  <QueryClientProvider client={queryClient}>
    <App />
  </QueryClientProvider>
</ConfigProvider>
```

No Tailwind.

- [ ] **Step 7: Verify Task 1**

```bash
npm run test:run
npm run typecheck
npm run build
```
Expected: all exit 0 and `frontend/dist/index.html` exists.

- [ ] **Step 8: Commit Task 1**

```bash
git add frontend
git commit -m "feat: scaffold clipatlas web frontend"
```

---

### Task 2: Build typed API boundary and Chinese error normalization

**Files:**
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/api/errors.ts`
- Create: `frontend/src/api/health.ts`
- Create: `frontend/src/api/projects.ts`
- Create: `frontend/src/api/library.ts`
- Create: `frontend/src/api/search.ts`
- Create: `frontend/src/api/speech.ts`
- Create: `frontend/src/api/roughCut.ts`
- Create: `frontend/src/api/exports.ts`
- Create: `frontend/src/api/settings.ts`
- Create: `frontend/src/api/system.ts`
- Create: `frontend/src/api/client.test.ts`
- Create: `frontend/src/utils/format.ts`
- Create: `frontend/src/utils/statusMaps.ts`

**Interfaces:**

```ts
export class ApiError extends Error {
  status: number
  code?: string
}

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T>
```

System functions:

```ts
openExportFolder(planId: string): Promise<{status: 'opened'}>
openJianying(): Promise<{status: 'launched'}>
```

No frontend API takes an export folder path.

- [ ] **Step 1: Write failing API client tests**

```ts
it('parses ClipAtlas stable error envelope', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
    JSON.stringify({ error: { code: 'speech_rate_limited', message: 'rate limited' } }),
    { status: 503, headers: { 'Content-Type': 'application/json' } },
  )))

  await expect(apiRequest('/api/v1/narration/tts')).rejects.toMatchObject({
    status: 503,
    code: 'speech_rate_limited',
  })
})
```

Also test JSON success, 204, FastAPI `{detail: ...}`, validation detail array, and network failure.

- [ ] **Step 2: Run RED**

```bash
npm run test:run -- src/api/client.test.ts
```
Expected: FAIL because client is absent.

- [ ] **Step 3: Implement `apiRequest`**

Rules:
- same-origin relative paths;
- default `Accept: application/json`;
- set JSON content type only for JSON bodies, not `FormData`;
- parse `{error:{code,message}}` before FastAPI detail;
- preserve HTTP status and stable code;
- technical message available to expandable detail, not primary copy.

- [ ] **Step 4: Define DTOs matching backend JSON**

At minimum:
- Project;
- LibraryRoot, LibraryItem, LibraryItemStatus;
- VideoAsset, VideoAnnotationStats, VideoDetailResponse, VideoSegment, SemanticAnnotation, SegmentPage;
- SemanticSearchHit;
- SpeechProviderDescriptor, VoiceDescriptor, SpeechProfile;
- NarrationTrack, NarrationUnit, NarrationWordTiming, ProjectNarrationItem;
- RoughCutPlan, ScriptBeat, RoughCutClip, CandidateScore;
- OTIO/Jianying artifact;
- PublicSettings/UpdateSettingsResponse.

Do not translate field names inside DTOs.

- [ ] **Step 5: Implement API module functions**

Representative signatures:

```ts
listProjects(): Promise<Project[]>
createProject(input: CreateProjectInput): Promise<Project>
getLibraryItems(params: LibraryItemsParams): Promise<LibraryItem[]>
getLibraryItem(itemId: string): Promise<LibraryItem>
getVideo(videoId: string): Promise<VideoDetailResponse>
getVideoSegments(videoId: string, limit: number, offset: number): Promise<SegmentPage>
searchSegments(q: string, limit: number): Promise<SemanticSearchHit[]>
listProjectNarrations(projectId: string): Promise<ProjectNarrationItem[]>
createTtsNarration(input: CreateTtsInput): Promise<NarrationTrackResponse>
createRoughCutPlan(input: CreateRoughCutInput): Promise<RoughCutPlan>
exportJianying(input: ExportJianyingInput): Promise<JianyingDraftArtifact>
getSettings(): Promise<PublicSettings>
updateSettings(input: SettingsPatch): Promise<UpdateSettingsResponse>
openExportFolder(planId: string): Promise<{status: 'opened'}>
openJianying(): Promise<{status: 'launched'}>
```

- [ ] **Step 6: Add format/status tests**

`formatDuration(222680)` -> `03:42.680`.

Library mapping:

```text
QUEUED -> 等待处理
PROBING -> 读取视频信息
SCENE_DETECTION -> 镜头切分
FRAME_EXTRACTION -> 画面提取
COMPLETED -> 处理完成
FAILED -> 处理失败
MISSING -> 文件丢失
```

Timing mapping:

```text
word_exact -> 词级精确
unit_exact -> 句级精确
aligned -> 已对齐
track_only -> 仅总时长
estimated -> 估算
```

- [ ] **Step 7: Verify and commit Task 2**

```bash
npm run test:run
npm run typecheck
git add frontend/src/api frontend/src/utils
git commit -m "feat: add typed frontend api client"
```

---

### Task 3: Build AppShell, routing, project state, and project switcher

**Files:**
- Create: `frontend/src/app/router.tsx`
- Create: `frontend/src/components/AppShell.tsx`
- Create: `frontend/src/components/ProjectSwitcher.tsx`
- Create: `frontend/src/components/PageHeader.tsx`
- Create: `frontend/src/components/LoadingBlock.tsx`
- Create: `frontend/src/components/ErrorBlock.tsx`
- Create: `frontend/src/components/EmptyState.tsx`
- Create: `frontend/src/stores/useAppStore.ts`
- Create: `frontend/src/features/projects/ProjectDialog.tsx`
- Create: `frontend/src/components/AppShell.test.tsx`
- Modify: `frontend/src/app/App.tsx`

**Interfaces:**

```ts
type AppState = {
  currentProjectId: string | null
  setCurrentProjectId: (id: string | null) => void
}
```

Persist only current project id under `clipatlas.app.v0.1`.

Routes:

```text
/                                  工作台
/library                           素材库
/library/items/:itemId             素材详情
/library/items/:itemId/segments    片段标注
/search                            素材搜索
/narration                         文案与旁白
/rough-cut                         自动粗剪
/rough-cut/:planId                 粗剪结果
/settings                          设置
```

- [ ] **Step 1: Write navigation/project tests**

Assert exactly six primary labels:

```text
工作台
素材库
素材搜索
文案与旁白
自动粗剪
设置
```

Assert project selection only stores id, not Project objects.

- [ ] **Step 2: Run RED**

```bash
npm run test:run -- src/components/AppShell.test.tsx
```

- [ ] **Step 3: Implement project restore behavior**

On load:
1. fetch projects;
2. keep persisted id if still present;
3. otherwise select first project;
4. if none, show create action and gracefully disable project-dependent work.

Never invent client-side UUIDs.

Project dialog supports create and rename/description edit.

- [ ] **Step 4: Add health status**

Poll `/health` every 30 seconds while page is visible.

Chinese copy:
- `服务正常`;
- `服务未连接`.

- [ ] **Step 5: Verify and commit Task 3**

```bash
npm run test:run
npm run typecheck
git add frontend/src/app frontend/src/components frontend/src/stores frontend/src/features/projects
git commit -m "feat: add chinese workbench shell and project context"
```

---

### Task 4: Implement workflow Dashboard, not BI

**Files:**
- Create: `frontend/src/features/dashboard/DashboardPage.tsx`
- Create: `frontend/src/features/dashboard/NextStepCard.tsx`
- Create: `frontend/src/features/dashboard/DashboardPage.test.tsx`
- Modify: `frontend/src/app/router.tsx`

**Interfaces:**
- Consumes current project id, library summary, project narration list, existing active RoughCut endpoint.
- Does not require P1 dashboard aggregation API.

- [ ] **Step 1: Write next-step state tests**

Priority:
1. no project -> `创建项目`;
2. no library roots/items -> `添加素材`;
3. library still processing or failed -> `查看素材处理`;
4. no active narration -> `准备文案与旁白`;
5. active narration but no active plan -> `生成自动粗剪`;
6. active plan -> `检查粗剪结果`.

404 from active-plan endpoint means “尚未生成”, not page failure.

- [ ] **Step 2: Run RED**

```bash
npm run test:run -- src/features/dashboard/DashboardPage.test.tsx
```

- [ ] **Step 3: Implement compact workflow cards**

Show:
- current project;
- global library processing counts;
- current narration source + real duration;
- active rough-cut revision + duration;
- one `继续下一步` action.

No charts and no persisted export-history card.

- [ ] **Step 4: Verify and commit Task 4**

```bash
npm run test:run -- src/features/dashboard/DashboardPage.test.tsx
npm run typecheck
git add frontend/src/features/dashboard frontend/src/app/router.tsx
git commit -m "feat: add workflow dashboard"
```

---

### Task 5: Implement Library list and material detail

**Files:**
- Create: `frontend/src/features/library/LibraryPage.tsx`
- Create: `frontend/src/features/library/LibraryRootDialog.tsx`
- Create: `frontend/src/features/library/LibraryItemTable.tsx`
- Create: `frontend/src/features/library/LibraryItemPage.tsx`
- Create: `frontend/src/features/library/LibraryPage.test.tsx`
- Modify: `frontend/src/app/router.tsx`

**Interfaces:**
- Consumes Library root/list/summary/scan/retry, Stage-A LibraryItem detail, Stage-A video detail.

- [ ] **Step 1: Write Library tests**

Test:
- add-directory sends exact path and recursive flag;
- status filter maps to backend status query;
- FAILED row shows `重试`;
- retry invalidates item + summary queries;
- non-failed rows do not show retry;
- library summary controls whether polling continues.

- [ ] **Step 2: Run RED**

```bash
npm run test:run -- src/features/library/LibraryPage.test.tsx
```

- [ ] **Step 3: Implement query keys and polling**

```ts
['library', 'roots']
['library', 'items', filters]
['library', 'summary']
['library', 'item', itemId]
['video', videoId]
```

Poll items/summary every 2 seconds while summary has any count in:

```text
QUEUED
PROBING
SCENE_DETECTION
FRAME_EXTRACTION
```

Stop high-frequency polling when no non-terminal work remains or page is hidden/unmounted.

- [ ] **Step 4: Implement material detail**

Display:
- filename;
- full source path secondary/copyable;
- Chinese processing status;
- size and last error when relevant;
- duration/resolution/fps when `video_id` exists;
- Segment total;
- effective AI annotation count;
- effective HUMAN annotation count;
- locked annotation count;
- `查看片段标注`.

No video tag, thumbnail strip, canvas, or preview.

- [ ] **Step 5: Verify and commit Task 5**

```bash
npm run test:run -- src/features/library/LibraryPage.test.tsx
npm run typecheck
git add frontend/src/features/library frontend/src/app/router.tsx
git commit -m "feat: add material library workbench"
```

---

### Task 6: Implement Segment inspection and human annotation correction

**Files:**
- Create: `frontend/src/features/annotation/SegmentAnnotationPage.tsx`
- Create: `frontend/src/features/annotation/AnnotationCard.tsx`
- Create: `frontend/src/features/annotation/AnnotationEditDrawer.tsx`
- Create: `frontend/src/features/annotation/SegmentAnnotationPage.test.tsx`
- Modify: `frontend/src/app/router.tsx`

**Interfaces:**
- Consumes Stage-A paginated Segment list and existing annotation PATCH.
- Uses server-returned effective annotation; frontend never selects HUMAN vs AI.

- [ ] **Step 1: Write correction tests**

Test AI current annotation -> edit -> PATCH -> HUMAN response.

Assert:
- changed fields only are PATCHed;
- `已由人工修正` shown on HUMAN response;
- `素材索引已更新` only when `embedding_updated=true`;
- failure state says `人工修正已保存，但素材索引更新失败` when annotation save succeeded but embedding update response indicates false;
- Segment and semantic-search query keys invalidated;
- locked toggle uses same PATCH contract.

- [ ] **Step 2: Run RED**

```bash
npm run test:run -- src/features/annotation/SegmentAnnotationPage.test.tsx
```

- [ ] **Step 3: Implement paginated cards**

Default `limit=50`, Ant Design pagination.

Display:
- exact `start → end`;
- description;
- characters/actions/scene/emotions/objects/OCR;
- shot type/camera motion;
- confidence;
- source `AI 标注` or `人工标注`;
- revision;
- lock state.

- [ ] **Step 4: Implement edit drawer**

Array fields accept comma/newline input, trim blanks, preserve user order, no alphabetical reorder.

Default UI hides provider/model/raw payload.

- [ ] **Step 5: Verify and commit Task 6**

```bash
npm run test:run -- src/features/annotation/SegmentAnnotationPage.test.tsx
npm run typecheck
git add frontend/src/features/annotation frontend/src/app/router.tsx
git commit -m "feat: add human annotation correction ui"
```

---

### Task 7: Implement natural-language material search

**Files:**
- Create: `frontend/src/features/search/SearchPage.tsx`
- Create: `frontend/src/features/search/SearchResultCard.tsx`
- Create: `frontend/src/features/search/SearchPage.test.tsx`
- Modify: `frontend/src/app/router.tsx`

**Interfaces:**
- Consumes existing `GET /api/v1/search/segments?q=&limit=`.

- [ ] **Step 1: Write search tests**

Assert:
- blank query does not call API;
- Enter/button submit trimmed query;
- result shows source filename, exact source range, score %, effective description and primary tags;
- embedding provider/model/dimensions are absent from normal result DOM;
- `查看标注` navigates to the source material annotation view and highlights/locates the Segment without playing media.

- [ ] **Step 2: Run RED**

```bash
npm run test:run -- src/features/search/SearchPage.test.tsx
```

- [ ] **Step 3: Implement search-on-submit**

Default limit 20. Do not search every keystroke.

Display score:

```ts
`${Math.round(hit.score * 100)}%`
```

Never rerank by rounded value.

- [ ] **Step 4: Verify and commit Task 7**

```bash
npm run test:run -- src/features/search/SearchPage.test.tsx
npm run typecheck
git add frontend/src/features/search frontend/src/app/router.tsx
git commit -m "feat: add semantic material search ui"
```

---

### Task 8: Implement 文案与旁白 for TTS and imported narration

**Files:**
- Create: `frontend/src/features/narration/NarrationPage.tsx`
- Create: `frontend/src/features/narration/ScriptEditor.tsx`
- Create: `frontend/src/features/narration/SpeechProfileForm.tsx`
- Create: `frontend/src/features/narration/NarrationHistory.tsx`
- Create: `frontend/src/features/narration/ImportNarrationForm.tsx`
- Create: `frontend/src/features/narration/NarrationPage.test.tsx`
- Modify: `frontend/src/app/router.tsx`

**Interfaces:**
- Consumes providers/voices/Profile create-update-randomize, Stage-A Profile list, TTS/import, Stage-A Narration list, activate narration.
- No audio player is introduced in V0.1 because the approved spec has no browser audio-serving contract.

- [ ] **Step 1: Write page tests**

Cover:
- no project -> `请先创建或选择项目`;
- provider selection loads voices;
- custom `voice_id` accepted even if not in returned voice list;
- gender/age/speed/pitch/volume/emotion/style/instruction/locked preserved in Profile request;
- random button invokes backend randomize endpoint;
- TTS uses saved `speech_profile_id`, current project id and exact script;
- import uses `FormData` and exact script;
- activation refetches narration list;
- active track displays real duration and timing quality.

- [ ] **Step 2: Run RED**

```bash
npm run test:run -- src/features/narration/NarrationPage.test.tsx
```

- [ ] **Step 3: Implement two modes**

```text
AI 配音
上传真人旁白
```

AI basic form:
- 语音服务;
- 声音;
- 性别;
- 年龄感觉;
- 语速;
- 音高;
- 音量;
- 情绪;
- 风格;
- 锁定此声音方案;
- 随机声音.

Advanced collapse:
- 自定义 voice_id;
- instruction;
- provider/model diagnostic text.

- [ ] **Step 4: Map stable speech codes to Chinese actionable copy**

```text
speech_auth_failed            -> 语音服务认证失败，请检查设置中的 API Key。
speech_rate_limited           -> 语音服务请求过于频繁，请稍后重试。
speech_request_failed         -> 语音服务调用失败。
speech_audio_invalid          -> 返回的音频无效，未生成旁白。
speech_configuration_invalid  -> 当前语音配置不可用，请检查声音和参数。
speech_provider_unavailable   -> 尚未配置可用的语音服务。
```

Also render 422 field validation and 409 state conflicts as Chinese primary text with expandable technical detail.

- [ ] **Step 5: Implement history**

Each track:
- `AI 配音` / `真人旁白`;
- duration;
- timing quality;
- revision;
- created time;
- active state;
- `设为当前旁白` when inactive.

For `track_only`, display `只有总时长，当前不能用于句级自动粗剪`.

- [ ] **Step 6: Verify and commit Task 8**

```bash
npm run test:run -- src/features/narration/NarrationPage.test.tsx
npm run typecheck
git add frontend/src/features/narration frontend/src/app/router.tsx
git commit -m "feat: add script and narration workbench"
```

---

### Task 9: Implement automatic rough-cut generation and result inspection

**Files:**
- Create: `frontend/src/features/roughcut/RoughCutPage.tsx`
- Create: `frontend/src/features/roughcut/RoughCutResultPage.tsx`
- Create: `frontend/src/features/roughcut/BeatResultCard.tsx`
- Create: `frontend/src/features/roughcut/RoughCutPage.test.tsx`
- Create: `frontend/src/features/roughcut/RoughCutResultPage.test.tsx`
- Modify: `frontend/src/app/router.tsx`

**Interfaces:**
- Consumes active narration/list, create plan, active plan, get plan.
- Does not implement P1 candidate replacement.

- [ ] **Step 1: Write generation tests**

Assert:
- no active narration -> generation disabled;
- known `track_only` / `estimated` timing quality shows not-ready explanation;
- Top-K defaults 12;
- all-material mode sends no video restriction;
- specified-material mode sends selected `video_ids` exactly;
- successful generation navigates to `/rough-cut/{plan.id}`.

- [ ] **Step 2: Run RED**

```bash
npm run test:run -- src/features/roughcut/RoughCutPage.test.tsx
```

- [ ] **Step 3: Implement generation page**

Show active narration source/real duration/revision, material scope and Top-K.

Planner weights remain hidden.

Specified-material picker labels COMPLETED LibraryItems by filename/path, never UUID-first.

- [ ] **Step 4: Write result tests**

Assert **文案段落 → 已选择素材** cards, not timeline bars.

Each group displays:
- text;
- narration range;
- target duration;
- source filename;
- original source in/out;
- score;
- selection reason;
- collapsible score breakdown.

Assert no normal UI labels `V1`, `A1`, `轨道`, `剪辑时间轴` or trim handles.

- [ ] **Step 5: Implement display-only Beat grouping**

Group `plan.clips` by `beat_id`, preserve `plan.beats.sequence` and clip timeline order. Do not recompute or alter durations/source windows.

- [ ] **Step 6: Map rough-cut errors**

```text
rough_cut_unavailable        -> 自动粗剪服务当前不可用。
rough_cut_not_ready          -> 当前旁白或配置还不能生成粗剪。
rough_cut_retrieval_failed   -> 素材检索失败，请检查语义索引服务。
rough_cut_planning_failed    -> 自动粗剪生成失败，未修改已有结果。
```

- [ ] **Step 7: Verify and commit Task 9**

```bash
npm run test:run -- src/features/roughcut
npm run typecheck
git add frontend/src/features/roughcut frontend/src/app/router.tsx
git commit -m "feat: add automatic rough cut review ui"
```

---

### Task 10: Add OTIO/Jianying export and trusted local handoff

**Files:**
- Create: `frontend/src/features/export/ExportPanel.tsx`
- Create: `frontend/src/features/export/ExportPanel.test.tsx`
- Modify: `frontend/src/features/roughcut/RoughCutResultPage.tsx`

**Interfaces:**
- Consumes existing export API + Stage-A:
  - `POST /api/v1/system/open-export-folder` with `plan_id` only;
  - `POST /api/v1/system/open-jianying` with no arbitrary args.

- [ ] **Step 1: Write export tests**

Cover:
- OTIO sends plan id and shows returned output path;
- Jianying defaults 1920×1080 and project-derived draft name;
- `/` and `\` in draft name rejected client-side consistent with backend;
- successful Jianying export shows draft name, duration, output path, mode, backend version;
- `打开草稿目录` calls `openExportFolder(plan.id)` and does **not** send artifact `output_path`;
- `打开剪映` calls `openJianying()`;
- export actions never mutate/recreate the RoughCutPlan.

- [ ] **Step 2: Run RED**

```bash
npm run test:run -- src/features/export/ExportPanel.test.tsx
```

- [ ] **Step 3: Implement export panel at result-page bottom**

No seventh navigation item.

Resolution presets:

```text
1920 × 1080
1080 × 1920
```

Advanced custom width/height optional.

If the backend says the plan has no current-process registered artifact (for example after application restart), show:

```text
当前启动中没有可打开的草稿记录，请重新生成剪映草稿后再打开目录。
```

Do not fall back to sending a local path from the browser.

- [ ] **Step 4: Map Jianying errors**

```text
jianying_unavailable          -> 剪映草稿导出服务不可用。
jianying_dependency_missing   -> 缺少剪映草稿依赖，请检查安装。
jianying_not_configured       -> 尚未完成剪映路径配置。
jianying_media_unsupported    -> 当前素材无法写入剪映草稿。
jianying_write_failed         -> 剪映草稿写入失败，已有粗剪结果未被修改。
```

- [ ] **Step 5: Verify and commit Task 10**

```bash
npm run test:run -- src/features/export/ExportPanel.test.tsx
npm run typecheck
git add frontend/src/features/export frontend/src/features/roughcut/RoughCutResultPage.tsx
git commit -m "feat: add otio and jianying export handoff"
```

---

### Task 11: Implement real Settings page

**Files:**
- Create: `frontend/src/features/settings/SettingsPage.tsx`
- Create: `frontend/src/features/settings/SettingsSection.tsx`
- Create: `frontend/src/features/settings/SecretField.tsx`
- Create: `frontend/src/features/settings/SettingsPage.test.tsx`
- Modify: `frontend/src/app/router.tsx`

**Interfaces:**
- Consumes Stage-A GET/PATCH settings.
- No provider hot reload.

- [ ] **Step 1: Write settings tests**

Four groups:
1. 视频理解服务;
2. 语义索引服务;
3. 语音服务;
4. 剪映.

Secret behavior:
- GET shows only `已配置` / `未配置`;
- password input empty on load;
- blank password field is omitted from PATCH;
- new secret is sent only when user typed a nonblank replacement;
- clear requires explicit `清除已保存密钥` action, which sends the backend clear flag;
- response never repopulates password input.

Environment override copy:

```text
由环境变量管理；本机配置不会覆盖当前环境变量。
```

- [ ] **Step 2: Run RED**

```bash
npm run test:run -- src/features/settings/SettingsPage.test.tsx
```

- [ ] **Step 3: Implement settings form**

No arbitrary environment key/value editor.

After successful save:

```text
设置已保存。重启 ClipAtlas 后生效。
```

No fake “立即应用”.

- [ ] **Step 4: Verify and commit Task 11**

```bash
npm run test:run -- src/features/settings/SettingsPage.test.tsx
npm run typecheck
git add frontend/src/features/settings frontend/src/app/router.tsx
git commit -m "feat: add local runtime settings ui"
```

---

### Task 12: Serve built SPA from FastAPI without shadowing API/docs

**Files:**
- Create: `clipatlas/web.py`
- Modify: `clipatlas/main.py`
- Create: `tests/api/test_frontend_static.py`
- Modify: `.gitignore` if `frontend/dist` is not committed.

**Interfaces:**

```python
mount_frontend(app: FastAPI, dist_dir: Path) -> None
```

- `/api/*`, `/health`, `/docs`, `/openapi.json` remain API routes.
- `/assets/*` serves Vite assets.
- non-API browser routes fall back to `index.html`.

- [ ] **Step 1: Write static-serving tests**

Temporary fake dist:

```text
dist/index.html
dist/assets/app.js
```

Assert:
- `/` -> index;
- `/library/items/123` -> same SPA index;
- `/assets/app.js` -> asset;
- `/health` -> JSON;
- unknown `/api/v1/not-real` -> API 404, never index;
- missing dist -> API still starts.

- [ ] **Step 2: Run RED**

```bash
pytest tests/api/test_frontend_static.py -v
```

- [ ] **Step 3: Implement explicit frontend mount helper**

Do not root-mount `StaticFiles` before APIs.

Behavior:
1. mount `/assets` if dist exists;
2. final catch-all GET after API routers;
3. API-prefixed paths remain API 404;
4. no arbitrary filesystem serving.

Default dist root points to repository/local packaged `frontend/dist`; allow `CLIPATLAS_FRONTEND_DIST` override for packaging/tests.

- [ ] **Step 4: Verify and commit Task 12**

```bash
pytest tests/api/test_frontend_static.py tests/api/test_health.py -v
cd frontend && npm run build
cd ..
git add clipatlas/web.py clipatlas/main.py tests/api/test_frontend_static.py .gitignore
git commit -m "feat: serve react workbench from fastapi"
```

---

### Task 13: Add one-command local launcher and browser open

**Files:**
- Create: `clipatlas/cli.py`
- Modify: `pyproject.toml`
- Create: `tests/test_cli.py`
- Modify: `README.md`

**Interfaces:**

```text
clipatlas
clipatlas --no-browser
```

Default bind `127.0.0.1:8000`.

- [ ] **Step 1: Write CLI tests with injected side effects**

Defaults:

```text
host = 127.0.0.1
port = 8000
open_browser = true
```

Tests do not start real Uvicorn/browser.

- [ ] **Step 2: Run RED**

```bash
pytest tests/test_cli.py -v
```

- [ ] **Step 3: Implement console script**

`pyproject.toml`:

```toml
[project.scripts]
clipatlas = "clipatlas.cli:main"
```

Behavior:
- helper thread polls `http://127.0.0.1:<port>/health` with bounded retries;
- first 200 -> `webbrowser.open(root_url)` once;
- foreground `uvicorn.run("clipatlas.main:app", host=host, port=port)`;
- `--no-browser` skips helper.

No daemon/service install.

- [ ] **Step 4: Update README**

Development:

```text
Terminal 1: uvicorn clipatlas.main:app --reload
Terminal 2: cd frontend && npm run dev
```

Production-like local:

```text
cd frontend
npm ci
npm run build
cd ..
pip install -e ".[dev]"
clipatlas
```

Packaged users will consume built assets and do not need Node.

- [ ] **Step 5: Verify and commit Task 13**

```bash
pytest tests/test_cli.py tests/api/test_frontend_static.py -v
ruff check clipatlas/cli.py clipatlas/web.py tests/test_cli.py tests/api/test_frontend_static.py
mypy clipatlas/cli.py clipatlas/web.py
git add clipatlas/cli.py pyproject.toml tests/test_cli.py README.md
git commit -m "feat: add one-command local workbench launcher"
```

---

### Task 14: End-to-end frontend contract smoke test and full verification

**Files:**
- Create: `frontend/src/app/WorkflowSmoke.test.tsx`
- Modify: `README.md` only for corrections found during verification.

- [ ] **Step 1: Add mocked workflow smoke test**

Cover UI wiring:

```text
create/select project
→ library state visible
→ open material detail/annotation
→ semantic search
→ script + SpeechProfile + active narration
→ create rough cut
→ review Beat/material result
→ export Jianying
→ open generated draft folder using plan id
→ launch Jianying
```

The test mocks API responses and does not implement backend algorithms.

- [ ] **Step 2: Run all frontend gates**

```bash
cd frontend
npm run test:run
npm run typecheck
npm run build
```
Expected: all exit 0.

- [ ] **Step 3: Run full Python gates because shared wiring/packaging changed**

```bash
cd ..
ruff check clipatlas tests
mypy clipatlas
pytest -v
```
Expected: all exit 0.

- [ ] **Step 4: Local browser smoke test**

```bash
clipatlas --no-browser
```

Verify:
- exactly six Chinese primary nav entries;
- `/docs` still works;
- project create/switch/edit;
- library and deep-linked material detail;
- paginated Segments + annotation correction;
- no video player/timeline UI;
- semantic search;
- narration and active real duration;
- rough-cut cards;
- Settings save + restart alert;
- nested-route browser refresh works.

- [ ] **Step 5: Windows handoff smoke test only**

On already accepted Windows/Jianying Pro 10.8 environment:
- generate Jianying draft through existing accepted export path;
- click `打开草稿目录`; backend resolves current-process registered artifact by plan id and Explorer opens it;
- click `打开剪映`; configured Jianying starts;
- confirm draft still opens for manual editing.

Do **not** repeat completed A-E or Jianying timeline black-box verification unless a real export regression appears.

- [ ] **Step 6: Commit smoke test/docs corrections**

```bash
git add frontend/src/app/WorkflowSmoke.test.tsx README.md
git commit -m "test: verify chinese workbench workflow"
```

---

## Definition of Done

Stage B is complete only when:

1. `frontend/` builds and FastAPI serves it.
2. Normal UI is Chinese and has exactly six primary navigation entries.
3. Project create/list/switch/edit works and current project id persists locally.
4. Library processing state, deep-linked material detail, Segment counts, effective AI/HUMAN annotation statistics, locked count, paginated Segments, retry and human correction work through backend APIs.
5. Semantic search displays backend-ranked canonical Segment hits without frontend reranking.
6. 文案与旁白 supports provider/voice/Profile controls, custom voice id, randomization, TTS, imported narration, history and activation.
7. Rough-cut generation uses active real narration and review is Beat → selected material cards, not an editing timeline.
8. OTIO/Jianying export is available from rough-cut result; opening a draft folder passes only plan id to the trusted backend registry; launching Jianying accepts no arbitrary command args.
9. Settings truly persist whitelisted configuration, secrets are never echoed, blank secret means unchanged, explicit clear action is required, and UI reports restart semantics/environment ownership.
10. `clipatlas` starts the local production-like workbench on `127.0.0.1` and can open the browser.
11. No video preview/player or editor timeline was introduced.
12. Frontend tests/typecheck/build and Python ruff/mypy/pytest all pass after integration.
13. Existing Windows Jianying Pro 10.8 black-box acceptance is not redundantly repeated; only the new UI/system-handoff path is manually checked.

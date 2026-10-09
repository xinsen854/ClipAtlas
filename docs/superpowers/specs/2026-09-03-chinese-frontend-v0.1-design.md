# ClipAtlas 中文前端 V0.1 设计规格

日期：2026-09-03
基线提交：`3c478aa65bd750658d6420d90d6ce4c96d1c41af`
设计分支：`design/chinese-frontend-v0.1`

## 1. 目标

为 ClipAtlas 增加第一版中文本机 Web 工作台。该工作台服务于已有的素材解析、语义标注、语义检索、旁白/TTS、自动粗剪、OTIO 和剪映草稿能力，不重新实现剪辑器。

产品定位：**AI 素材管理与自动粗剪工作台**。

第一版闭环：

本地素材 → 解析状态 → 标注检查/人工修正 → 语义检索 → 文案与旁白 → 自动粗剪 → 粗剪结果检查 → 剪映草稿 → 打开草稿目录/剪映。

## 2. 锁定边界

### 2.1 必须做

- 本机单用户。
- 中文 Web 工作台。
- React + TypeScript + Vite。
- React Router。
- TanStack Query 管理服务端状态。
- Zustand 只保存少量客户端全局状态。
- Ant Design 作为组件基础。
- 前端 build 后由 FastAPI 提供静态资源。
- 后续可封装 Tauri/Windows EXE。
- 工作台、项目、素材库、标注修正、语义检索、文案/旁白、自动粗剪、粗剪检查、导出和设置。
- 已有精确时间轴、Segment、source in/out、Narration timing、RoughCut timeline 保持在后端数据模型中。

### 2.2 明确不做

- 登录、注册、权限。
- 视频播放器。
- 视频预览。
- 剪辑时间轴 UI。
- 多轨编辑。
- 拖拽裁切。
- 转场、字幕、调色、BGM、音效编辑。
- 重新实现剪映。
- 修改或重测已经通过的 Semantic Retrieval、Narration/TTS、RoughCut、OTIO、Jianying 核心，除非出现真实回归。

## 3. 当前后端能力基线

当前 FastAPI 已挂载：

- `/api/v1/providers`
- `/api/v1/videos`
- `/api/v1/library`
- `/api/v1/search`
- `/api/v1/speech`
- `/api/v1/narration`
- `/api/v1/rough-cut`
- `/api/v1/exports`
- `/health`

当前 Provider、Embedding、TTS、剪映等运行配置主要从环境变量读取，并在应用启动阶段构建 runtime。因此 V0.1 设置页若要真正可用，必须增加一个受控的本机配置层，不能只做一个“看起来能保存”的前端表单。

## 4. 产品数据边界

### 4.1 素材库是全局资源

素材库不属于某一个项目。一次解析、标注和 Embedding 后，可供多个项目复用。

禁止为了项目管理复制视频、Segment、Annotation 或 Embedding。

### 4.2 Project 是创作任务上下文

Project 聚合：

- 文案相关工作上下文。
- SpeechProfile。
- NarrationTrack。
- RoughCutPlan。
- 导出操作上下文。

项目在生成 RoughCut 时可通过 `video_ids` 临时限定素材范围，但 V0.1 不引入复杂的“项目素材库复制/归属”模型。

### 4.3 ProjectStore

新增独立轻量 ProjectStore，建议 SQLite 默认路径：

`./data/projects/projects.sqlite3`

最少字段：

- id
- name
- description（可空）
- created_at
- updated_at

V0.1 不做删除项目，避免引入跨 Narration/RoughCut/Export 的级联删除语义。

## 5. 信息架构

一级导航固定 6 个区域：

1. 工作台
2. 素材库
3. 素材搜索
4. 文案与旁白
5. 自动粗剪
6. 设置

`当前项目` 是全局上下文，不作为一级菜单。

标注修正从 `素材库 → 素材详情 → 片段标注` 进入。

粗剪结果检查属于 `自动粗剪` 子页面。

导出属于粗剪结果页的后续操作，不增加一级菜单。

## 6. 全局应用框架

### 6.1 左侧导航

固定展示六个一级入口。

### 6.2 顶部全局栏

至少包含：

- 当前项目名称。
- 当前项目切换。
- 后端连接状态。
- 当前后台处理状态摘要（如有）。

不展示内部 UUID、Embedding dimensions 等实现字段。

### 6.3 状态管理

TanStack Query 负责：

- API 查询缓存。
- 重新获取。
- Mutation 后失效刷新。
- 加载/错误状态。
- 页面可见状态下的必要轮询。

Zustand 仅负责：

- 当前 `project_id`。
- UI 偏好。
- 少量跨页面临时选择。

禁止把服务端实体复制进 Zustand 形成第二套数据库。

## 7. 页面规格

### 7.1 工作台 `/`

目标：回答“现在做到哪一步，下一步做什么”。

展示：

- 当前项目。
- 全局素材库处理状态汇总。
- 当前项目旁白状态与真实时长。
- 当前项目 active RoughCut 状态。
- `继续下一步` 主操作。

“继续下一步”依据状态跳转：

- 没有素材 → 素材库。
- 素材未处理完成 → 素材库状态页。
- 没有当前旁白 → 文案与旁白。
- 有旁白但没有 RoughCut → 自动粗剪。
- 有 RoughCut → 粗剪结果。

V0.1 不要求持久化“最近剪映草稿历史”，避免为了首页额外引入 Export History 存储。

不做 BI 图表。

### 7.2 项目管理

项目不是一级菜单，但顶部项目切换器必须支持：

- 创建项目。
- 列出项目。
- 切换项目。
- 修改名称/描述。

不做删除、归档、协作和权限。

### 7.3 素材库 `/library`

能力：

- 添加本地素材目录。
- 查看素材目录。
- 触发扫描。
- 按状态筛选。
- 文件名搜索。
- 查看处理状态。
- FAILED 重试。
- 进入素材详情。

中文状态：

- QUEUED → 等待处理
- PROBING → 读取视频信息
- SCENE_DETECTION → 镜头切分
- FRAME_EXTRACTION → 画面提取
- COMPLETED → 处理完成
- FAILED → 处理失败
- MISSING → 文件丢失

隐藏 fingerprint、mtime_ns、processed_fingerprint 等内部字段。

### 7.4 素材详情 `/library/items/:itemId`

展示：

- 文件名。
- 文件路径。
- 处理状态。
- duration / width / height / fps（已完成且存在 catalog video 时）。
- Segment 总数。
- 有效 AI/HUMAN 标注统计。
- 人工锁定数量。
- 进入片段标注列表。

不放视频播放器。

### 7.5 片段标注 `/library/items/:itemId/segments`

必须分页，不一次加载长视频全部 Segment。

每个 Segment 显示：

- start/end。
- effective annotation description。
- characters。
- actions。
- scene。
- emotions。
- objects。
- OCR。
- shot_type。
- camera_motion。
- confidence。
- origin。
- revision。
- locked。

操作：

- 修改。
- 保存人工修正。
- 锁定/解锁。

保存成功明确反馈：

- 已保存人工修正。
- 素材索引已更新 / 索引更新失败。

有效 Annotation 继续遵守 Human > AI。

### 7.6 素材搜索 `/search`

输入：中文自然语言。

结果展示：

- 从 source_uri 提取的文件名。
- source start/end。
- 匹配度。
- effective_description。
- 场景/人物/动作/情绪等主要标签。
- 标注来源。
- `查看标注`。

隐藏 embedding provider/model/dimensions，仅开发诊断时可见。

第一版不播放命中片段。

### 7.7 文案与旁白 `/narration`

单页完成“文案 → 确定时长的旁白”。

顶部：文案编辑区。

旁白方式：

- AI 配音。
- 上传真人旁白。

AI 配音基础设置：

- 语音服务。
- 声音。
- 性别。
- 年龄风格。
- 语速。
- 音高。
- 音量。
- 情绪。
- 风格。
- 锁定声音方案。
- 随机声音。

高级设置折叠：

- custom voice_id。
- instruction。
- provider/model 诊断信息。

真人旁白：

- 上传音频。
- 对应文案。
- 导入。

历史 SpeechProfile / NarrationTrack 可按项目读取。

当前旁白卡片展示：

- 来源。
- duration_ms 格式化时长。
- timing_quality 中文映射。
- revision。
- 是否 active。

真实旁白 duration 是后续 RoughCut 权威时长。

### 7.8 自动粗剪 `/rough-cut`

展示当前 active Narration：

- 来源。
- 总时长。
- revision。

生成条件：必须存在 active Narration。

设置：

- 素材范围：全部素材 / 手动指定 video_ids。
- Top-K，默认 12。

Planner 内部权重 V0.1 不在普通 UI 暴露。

主操作：`生成自动粗剪`。

### 7.9 粗剪结果 `/rough-cut/:planId`

固定展示模型：**文案段落（ScriptBeat）→ 已选择素材**。

禁止做剪辑时间轴。

每段展示：

- 文案 text。
- 旁白 start/end。
- target duration。
- source_uri / 文件名。
- 原片 source in/out。
- score。
- selection_reason。
- 可折叠 score_breakdown。

V0.1 P0 只要求检查，不要求手工裁切。

`换一个素材` 是 P1 高价值功能。必须由后端暴露 planner 候选或正式替换操作；禁止前端复制 RoughCut 打分逻辑。

### 7.10 导出

位于粗剪结果页后续操作区。

支持：

- 导出 OTIO。
- 生成剪映草稿。

剪映输入：

- draft_name。
- width。
- height。

成功展示：

- 草稿名。
- output_path。
- mode。
- backend version。
- total duration。

按钮：

- 打开草稿目录。
- 打开剪映。

浏览器不能直接执行任意本机命令，因此这两个动作必须使用受限系统桥接 API。

### 7.11 设置 `/settings`

V0.1 设置必须是“真设置”，不是静态表单。

分组：

1. 视频理解服务。
2. Embedding 服务。
3. TTS 服务。
4. 剪映。

配置来源采用两层：

1. 本机配置文件。
2. 环境变量覆盖。

建议默认本机配置文件：

`./data/config/settings.json`

环境变量优先级高于本机配置。若某字段被环境变量覆盖，UI 显示“由环境变量管理”，不允许误导用户认为修改后会覆盖环境变量。

API Key 等 secret：

- 可写入本机配置。
- GET 不回显明文，只返回 `configured: true/false`。
- 前端留空表示“不修改现有 secret”。
- 明确清除 secret 必须使用单独的 clear 标志或操作，禁止把空字符串误解释为清除。

由于当前 runtime 在启动时构建，Provider/Embedding/TTS/剪映配置修改后 V0.1 返回 `restart_required=true`，界面提示“重启 ClipAtlas 后生效”。V0.1 不为了热重载去改写已稳定 runtime。

## 8. 已有 API 对照

### 8.1 素材库

- POST `/api/v1/library/roots`
- GET `/api/v1/library/roots`
- GET `/api/v1/library/items`
- GET `/api/v1/library/summary`
- POST `/api/v1/library/scan`
- POST `/api/v1/library/items/{item_id}/retry`
- GET `/api/v1/library/segments/{segment_id}/annotation`
- PATCH `/api/v1/library/segments/{segment_id}/annotation`

### 8.2 视频上传

- POST `/api/v1/videos`

V0.1 主工作流优先使用 Library Root；单文件上传为次级入口。

### 8.3 语义检索

- GET `/api/v1/search/segments?q=&limit=`

### 8.4 Speech / Narration

- GET `/api/v1/speech/providers`
- GET `/api/v1/speech/providers/{provider}/voices`
- POST `/api/v1/speech/profiles`
- PATCH `/api/v1/speech/profiles/{profile_id}`
- POST `/api/v1/speech/profiles/randomize`
- POST `/api/v1/narration/tts`
- POST `/api/v1/narration/import`
- GET `/api/v1/narration/{track_id}`
- POST `/api/v1/narration/{track_id}/activate`

### 8.5 RoughCut

- POST `/api/v1/rough-cut/plans`
- GET `/api/v1/rough-cut/plans/active?project_id=`
- GET `/api/v1/rough-cut/plans/{plan_id}`

### 8.6 Export

- POST `/api/v1/exports/otio`
- POST `/api/v1/exports/jianying`

## 9. Frontend Contract 最小缺口

这些接口只补 GUI 所需契约，不重写已验收核心。

### FC-01 Project API（P0）

- POST `/api/v1/projects`
- GET `/api/v1/projects`
- GET `/api/v1/projects/{project_id}`
- PATCH `/api/v1/projects/{project_id}`

使用独立 ProjectStore。V0.1 不提供 DELETE。

### FC-02 LibraryItem detail（P0）

- GET `/api/v1/library/items/{item_id}`

用于浏览器刷新深链接后恢复素材详情，不依赖上一页内存状态。

### FC-03 Video detail + Segment list（P0）

新增：

- GET `/api/v1/videos/{video_id}`
- GET `/api/v1/videos/{video_id}/segments?limit=&offset=`

`GET /videos/{video_id}` 返回视频基础信息与聚合统计，不返回大量 frame URI。

Segment list 返回：

- VideoSegment 基础字段。
- effective annotation 摘要或完整 effective annotation。

CatalogStore 已有 `get_ingested_video`、`get_video`、`get_effective_annotation` 能力，接口层可复用，不需要重写解析链。

### FC-04 项目 SpeechProfile 列表（P0）

- GET `/api/v1/projects/{project_id}/speech-profiles`

用于恢复声音方案与历史 revision。

### FC-05 项目 Narration 列表（P0）

- GET `/api/v1/projects/{project_id}/narrations`

响应必须能标明当前 active track，或提供等价 active 查询。

### FC-06 项目 RoughCut 历史（P1）

- GET `/api/v1/projects/{project_id}/rough-cut/plans`

P0 只依赖现有 active + get by id 即可跑通主链；历史列表随后补。

### FC-07 本机系统桥接（P0）

建议：

- POST `/api/v1/system/open-export-folder`
- POST `/api/v1/system/open-jianying`

安全边界：

- 不接受任意 shell 命令。
- 打开目录只接受后端已生成 artifact/plan 标识，后端自行解析受信 output_path；不允许前端传任意文件系统路径。
- 打开剪映只允许使用已配置的剪映安装位置。
- 禁止透传任意命令参数。

### FC-08 本机设置 API（P0）

建议：

- GET `/api/v1/settings`
- PATCH `/api/v1/settings`

返回：

- 非敏感有效配置。
- secret 是否已配置。
- 哪些字段被环境变量覆盖。
- `restart_required`。

PATCH 只允许白名单配置键，禁止写任意环境变量或任意文件。

配置写入后不尝试在进程内热替换 Provider Registry；V0.1 采用“保存 → 提示重启”策略。

### FC-09 工作台聚合摘要（P1）

可后加：

- GET `/api/v1/projects/{project_id}/dashboard`

首版可由现有 summary + narration list + active rough-cut 查询组合完成，不是 P0 阻断项。

### FC-10 RoughCut 候选替换（P1）

建议后续单独设计：

- GET `/api/v1/rough-cut/plans/{plan_id}/beats/{beat_id}/candidates`
- POST `/api/v1/rough-cut/plans/{plan_id}/beats/{beat_id}/selection`

必须明确新 RoughCut revision 行为后才能实现，禁止原地悄悄篡改已生成计划。

## 10. 前端目录结构

```text
frontend/
  src/
    app/
    api/
    components/
    features/
      project/
      library/
      annotation/
      search/
      narration/
      roughcut/
      export/
      settings/
    pages/
    stores/
    types/
```

按 feature 隔离业务。禁止把所有 API、表格和表单堆进一个页面文件。

## 11. 前后端部署

开发态：

- Vite dev server。
- FastAPI 独立运行。
- Vite proxy `/api` 到 FastAPI。

生产态：

- `frontend/dist` 由 FastAPI 提供。
- `/api/*` 保持 API 路由。
- 非 API SPA 路由回退到 `index.html`。

目标：一条本机命令启动 FastAPI + 前端静态工作台，并可自动打开浏览器。

Tauri 不是 V0.1 前置条件；Web 工作台稳定后再封装。

## 12. 错误处理

前端不得把所有错误统一成“请求失败”。

规则：

- 401 → 凭证无效/未授权。
- 429 → 上游限流，提示稍后重试。
- 已有上游失败/音频异常错误码 → 中文映射。
- 422 → 显示具体字段问题。
- 409 → 显示状态冲突及可执行下一步。
- 503 → 对应服务未配置。
- 技术 detail 放在可折叠“技术详情”，默认不显示英文堆栈。

不得改变 Hotfix C 已稳定的错误语义。

## 13. 轮询与后台任务

素材处理由现有 supervisor/worker 驱动。

V0.1 使用低频 HTTP 轮询，不引入 WebSocket：

- 素材列表/summary 页面可见时轮询。
- 页面不可见或离开后停止高频轮询。
- COMPLETED / FAILED / MISSING 等终态不做单项持续轮询。

## 14. 中文化

普通 UI 避免直接出现：

- Semantic Retrieval
- Embedding
- ScriptBeat
- RoughCutPlan
- source_in/source_out
- embedding dimensions

用户语言：

- 智能素材搜索
- 素材索引
- 文案段落
- 自动粗剪
- 原片位置
- 当前旁白

内部 API/type 继续英文，不要求后端中文化。

## 15. 实施顺序

### Stage A：Frontend Contract

P0 仅补：

1. ProjectStore + Project API。
2. LibraryItem detail。
3. Video detail + Segment list。
4. SpeechProfile list。
5. Narration list + active 状态。
6. SettingsStore/Settings API（保存后重启生效）。
7. 受限 system bridge。

禁止修改 Semantic Retrieval、TTS synthesis、RoughCut planner、OTIO、Jianying adapter 核心算法。

### Stage B：React 工作台

1. 前端骨架与 API client。
2. 项目上下文。
3. 素材库与处理状态。
4. Segment/Annotation 修正。
5. 语义搜索。
6. 文案与旁白。
7. 自动粗剪。
8. 粗剪检查。
9. OTIO/剪映导出。
10. 设置页。
11. 本机系统动作。
12. FastAPI 静态托管与单命令启动。

### Stage C：P1 增强

主链稳定后再做：

- RoughCut 历史列表。
- Dashboard 聚合 API。
- `换一个素材` 候选与 revision 流程。
- Tauri/Windows EXE 封装。

## 16. V0.1 验收标准

真实本机闭环：

1. 创建项目。
2. 添加本地素材目录。
3. 扫描并查看处理状态。
4. 刷新浏览器后素材详情深链接仍可恢复。
5. 打开某视频 Segment 分页列表。
6. 修改一个 Annotation，并看到 `embedding_updated` 结果。
7. 用中文自然语言检索素材。
8. 输入文案。
9. 选择/建立 SpeechProfile 并生成 TTS，或导入真人旁白。
10. 激活旁白并显示真实 duration。
11. 生成 RoughCutPlan。
12. 以“文案段落 → 已选择素材”检查 source in/out 与选择理由。
13. 导出 OTIO。
14. 生成剪映草稿。
15. 点击按钮打开该草稿目录。
16. 点击按钮启动已配置剪映。
17. 剪映 Pro 10.8 能继续打开并人工编辑该草稿。
18. 设置页修改一个白名单配置，正确保存并提示重启；secret 不被 GET 明文回显。

第 17 项只验证新前端接线未破坏已通过黑盒能力，不重复 A-E / Jianying adapter 底层验收。

## 17. 反回归边界

Frontend V0.1 不得为了 UI 方便而改写：

- Semantic Retrieval。
- Speech Profile 与动态 Provider 路由。
- Speech 稳定错误码。
- Human Annotation revision / Embedding 更新规则。
- RoughCut planner 选择与精确时间逻辑。
- OTIO builder。
- Jianying Adapter / portable draft。
- draft_name 路径安全。
- DashScope 音频下载大小限制。

若前端暴露真实回归，先建立回归证据，再单独处理对应核心。

## 18. 最终架构决策

V0.1：

**React + TypeScript + Vite + React Router + TanStack Query + Zustand + Ant Design**。

FastAPI 承担：

- API 服务。
- 生产态静态资源托管。
- 本机配置契约。
- 受限本机系统桥接。

ClipAtlas Web UI 负责“管理、检查、选择、触发”；剪映负责“人工精剪”。

# FineCut 独立模块设计

## 目标

在不重构 ClipAtlas 前半段稳定核心的前提下，把“智能精剪 + 外部工程 Workspace”建设为独立源码模块 `modules/finecut`，最后通过 ClipAtlas 内部极薄 Bridge 接入。

FineCut 可以独立开发、测试、保存 Timeline；未来可以整体拆成单独仓库。当前不要求 FineCut 脱离 ClipAtlas 单独启动。

## 基线

- 仓库：`xinsen854/ClipAtlas`
- 稳定基线：`visual-timeline-global-match-v1`
- 锁定 HEAD：`f5846e55e091cd67d1f4eddde0fafc446957f34b`
- 开发分支：`feat/intelligent-finecut-external-workspace-v0.1`
- 禁止修改 `main`
- 禁止修改稳定分支
- 禁止开 PR

## 总体架构

依赖方向只能是：

```text
ClipAtlas core
    |
    v
ClipAtlas FineCut Bridge
    |
    v
FineCut module
```

FineCut 不得 import `clipatlas.roughcut`、`clipatlas.director`、`clipatlas.retrieval`、`clipatlas.library`、`clipatlas.speech`。

ClipAtlas Bridge 可以同时认识 ClipAtlas domain 与 FineCut public models，负责把已有数据转换成 FineCut 输入。

## 源码布局

```text
modules/finecut/
  pyproject.toml
  finecut/
    __init__.py
    models.py
    store.py
    editing/
    effects/
    external/
    render/
  tests/
  ui/

clipatlas/integrations/finecut/
  __init__.py
  roughcut_bridge.py
  candidate_bridge.py
  routes.py
```

仅在当前需求真正需要文件时创建；不得为了“以后可能使用”一次性铺满目录。

## FineCut V0.1 自有数据

FineCut 只拥有：

- `TimelineDocument`
- `Track`
- `Clip`
- 编辑命令所需状态
- Undo/Redo 会话内存状态
- Workspace 状态
- Timeline 持久化
- effects / external resource / renderer 在相应 Phase 到来时的最小实现

FineCut 不拥有：

- 第二套素材库
- 第二套向量库
- 第二套视频解析
- 第二套 Director
- 第二套 Candidate Matrix
- 第二套 RoughCut
- 第二套 narration/word timing 生成链

## TimelineDocument

V0.1 当前字段：

```text
TimelineDocument
- version
- project_id
- source_plan_id
- width
- height
- fps
- duration_ms
- tracks

Track
- id
- kind: video | audio | text | overlay
- clips

Clip
- id
- source_id
- source_path
- timeline_start_ms
- duration_ms
- source_in_ms
- source_out_ms
- opacity
- volume
- transform
- effects
```

当前字段以运行代码为准；本阶段不因模型洁癖删除已经存在的字段，也不提前扩展效果合同。

禁止新增 SceneGraph、NodeGraph、RenderScheduler、PluginHost、GraphEngine、AnimationGraph、第二套 EventBus。

## RoughCut Bridge

`clipatlas/integrations/finecut/roughcut_bridge.py` 负责：

```text
RoughCutPlan -> TimelineDocument
```

必须满足：

```text
RoughCutClip.source_in_ms == Timeline Clip.source_in_ms
RoughCutClip.source_out_ms == Timeline Clip.source_out_ms
RoughCutClip.timeline_in_ms == Timeline Clip.timeline_start_ms
```

禁止重新计算 source range。

Bridge 不修改 RoughCutPlan，不修改 word timing，不重新调用任何 AI/API。

## S/A/B Candidate Bridge

候选真相仍在 ClipAtlas 现有 Candidate Matrix / RoughCutPlan 中。

FineCut 当前只消费运行代码已经提供的 `CandidateList / CandidateItem` 字段；候选显示等级映射为：

```text
DIRECT -> S
SUPPORT -> A
RELATED -> B
GENERIC -> Generic
SOURCE -> Fallback/Source
REUSE -> Fallback/Reuse
UNKNOWN -> 默认隐藏
REJECT / pollution blocked / illegal -> 不进入可选候选
```

`importance S/A/B` 保持原义，不参与候选显示等级映射。

CandidateItem 只透传 Candidate Matrix 已经存在的数据，包括 requirement/sentence/source quote、importance、media/source range、anchor、continuity、visual family、presentation type、已有各项 score、vector score 与 preliminary level；不新增 AI reason、explanation、recommendation score 或 thumbnail DTO。

点击当前旁白/镜头后只读取已有结果。禁止重新 embedding、重新解析、重新调用 Director、重新生成 S/A/B。

## Timeline 保存

FineCut 使用独立持久化，例如默认：

```text
./data/finecut/finecut.sqlite3
```

数据库只允许一张 timeline 表，只持久化最终 `TimelineDocument`。

V0.1 Undo/Redo 仅保存在当前会话内存，不持久化编辑命令历史。Workspace 当前模式如需恢复，优先使用前端本地状态；没有当前必要性时不新增 TimelineDocument metadata，也不另建状态表。

不得保存素材副本、向量、Candidate Matrix、S/A/B、Director 数据、RoughCut 副本或第三方缓存包。

## Workspace

只有一个 TimelineDocument、一个编辑状态、一个 Undo/Redo、一个保存系统。

Workspace A：智能精剪。

Workspace B：外部工程。

Workspace 切换仅改变布局与工具暴露，不建立第二条 Timeline。

## 外部资源

仅扫描用户明确选择的目录或用户确认后的自动发现路径。默认禁止全盘扫描。

JS/Lua 只能解析、读取配置、提取参数和映射；禁止直接执行未知 JS/Lua，禁止未知 exe/dll，禁止动态加载未知二进制插件，禁止 `shell=True`。

第三方原始字体、shader、Lua、JS、贴图、缓存包、账号、token、cookie 不得提交仓库。

## 热插拔定义

V0.1 只实现源码级/构建级可插拔：FineCut 模块存在时显示智能精剪入口并允许 mount；FineCut 模块不存在时 ClipAtlas 原功能仍可工作，入口隐藏或不可用。

不建设动态插件框架、插件发现、manifest、插件生命周期、插件市场、事件总线或二进制插件加载系统。

## 开发顺序

严格按：

1. TimelineDocument + RoughCut Bridge
2. 智能精剪只读界面
3. S/A/B 编辑能力：replace / trim / split / delete / undo / redo
4. Workspace 切换，同一 TimelineDocument
5. ExternalProjectImporter / Scanner / Catalog，只读扫描分类
6. 最小效果：text_pop / crossfade / spatial_rotate
7. 本地 MP4 导出

未完成并验证当前 Phase，不进入下一 Phase。

## 每个模块编码前的五项门禁

每写一个模块或抽象前必须回答：

1. 这段代码是否当前必须？
2. 现有代码或更普通的函数/dict 能否更简单地完成？
3. 是否严格位于 V0.1 制作清单和当前 Phase 内？
4. 是否因为过度思考而增加了并不存在的复杂度？
5. 是否提前加入未来功能、扩展点或通用框架？

任一项无法明确回答，停止编码，先缩小设计。

## 每个 Phase 完成自检

必须回答：

- 改了什么
- 为什么必须改
- 有没有修改前半段稳定核心
- 有没有重复现有能力
- 有没有第二套 Timeline
- 有没有第二套素材库
- 有没有第二套向量库
- 有没有新增 AI/API 调用
- 有没有执行未知外部脚本
- 有没有把第三方缓存提交仓库
- 有没有为了未来可能使用提前发明
- 有没有过度抽象
- 有没有绕过污染/素材合法性规则
- 测试结果
- git diff --stat

## V0.1 停止条件

满足既定 20 项完成定义后立即停止功能扩展，进入真实精剪黑盒测试。不得继续扩成传统剪辑器、完整 AE、完整第三方 runtime、插件商城、Agent Editor 或复杂关键帧系统。

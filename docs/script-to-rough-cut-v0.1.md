# ClipAtlas Script-to-Rough-Cut V0.1

## 目标

Script-to-Rough-Cut V0.1 把 ClipAtlas 已经存在的两套 canonical 数据真正连接起来：

```text
素材库 / 语义索引
        +
当前激活旁白 / 真实时间轴
        ↓
ScriptBeat
→ Top-K 语义检索
→ 结构化重排
→ 按真实旁白时长填充素材
→ RoughCutPlan
```

`RoughCutPlan` 是 ClipAtlas 的核心粗剪结果。它记录每一段素材来自哪里、从源视频哪一毫秒开始/结束、放在成片时间轴哪一毫秒开始/结束，以及为什么选择这段素材。

V0.1 **不直接写 OTIO，也不直接写剪映草稿**。OTIO / 剪映属于后续 Adapter 层。

---

## 1. 为什么旁白时间是权威

粗剪不重新估算文案时长，也不让素材长度反过来改变旁白。

自动粗剪读取：

```text
NarrationStore.get_active_track(project_id)
NarrationStore.list_units(track_id)
```

然后使用当前激活 `NarrationTrack` 的实测 `duration_ms` 与可用的 `NarrationUnit.start_ms / end_ms`。

核心规则：

> **旁白时间控制成片时间轴；素材适配旁白。**

这样用户修改 TTS 音色、语速、真人旁白或重新生成语音后，只要激活新的 NarrationTrack，再生成新的 RoughCutPlan，就不会继续拿旧文案时长剪素材。

---

## 2. 支持的 TimingQuality

V0.1 精确多 Beat 模式接受：

```text
WORD_EXACT
UNIT_EXACT
ALIGNED
```

另外允许一个明确的低精度降级路径：

```text
source_mode = IMPORTED
TimingQuality = TRACK_ONLY
```

此时真人旁白的整轨 `duration_ms` 仍是真实音频时长。Planner 只生成 **1 个覆盖 0..duration_ms 的整轨 ScriptBeat**，查询文本使用完整旁白文案；不会给原本没有时间码的 NarrationUnit 伪造句级或词级时间。

仍然拒绝：

```text
TTS + TRACK_ONLY
任意 source_mode + ESTIMATED
```

原因是 TTS 的 `TRACK_ONLY` 不符合正常 TTS 精确计时链，`ESTIMATED` 也不是实测声音时间。真人旁白完成对齐并变为 `ALIGNED` 后，会自动回到正常的句级多 Beat 粗剪。

---

## 3. ScriptBeat 与静音归属

`BeatBuilder` 不调用 LLM，不重写文案。

V0.1 在 `WORD_EXACT / UNIT_EXACT / ALIGNED` 模式下，每个 timed NarrationUnit 对应一个 ScriptBeat，`query_text` 默认就是该 Unit 的旁白文本。

`IMPORTED + TRACK_ONLY` 是唯一例外：所有原始 unit 仍保持未计时，只在粗剪层生成一个整轨 ScriptBeat，使用完整旁白文案做一次检索。

为了保证精确多 Beat 模式下最终画面从 `0` 连续覆盖到 `NarrationTrack.duration_ms`：

- 开头静音归第一个 Beat；
- 结尾静音归最后一个 Beat；
- 两个 Unit 中间如果存在静音，按中点切分；
- 原本连续的 Unit 边界保持不变。

例如：

```text
Unit A: 200..1000 ms
Unit B: 1400..2200 ms
Track:  0..2500 ms
```

400 ms 中间静音在 1200 ms 中点切开，最终 Beat：

```text
Beat A: 0..1200 ms
Beat B: 1200..2500 ms
```

不会出现成片时间轴空洞。

---

## 4. Top-K 检索，而不是直接拿第一名

每个 ScriptBeat 先调用一次现有 `SemanticSearchService.search()`：

```text
beat.query_text
→ Top-K canonical SemanticSearchHit
```

默认：

```text
top_k = 12
```

可通过 API 在 `1..100` 范围内调整。

SemanticSearchHit 已经包含：

```text
segment_id
video_id
source_uri
source_start_ms
source_end_ms
cosine score
effective SemanticAnnotation
```

因此 Planner 不重新猜源视频 in/out，也不允许模型擅自越过 canonical Segment 边界。

---

## 5. 结构化重排

V0.1 默认总分：

```text
0.58 * semantic_score
+ 0.08 * action_score
+ 0.08 * scene_score
+ 0.06 * emotion_score
+ 0.12 * duration_fit_score
+ 0.05 * quality_score
+ continuity_bonus
- reuse_penalty
```

### semantic_score

来自现有向量检索余弦相似度，并限制在 `0..1`。

### action / scene / emotion

V0.1 使用确定性词法特征，不额外调用 LLM：

- 英文 / 数字：小写词；
- 中文：单字 + 连续双字 gram；
- 分别与 `SemanticAnnotation.actions / scene / emotions` 计算 overlap coefficient。

这样结构化字段能参与重排，同时结果可审计、可复现。

### duration_fit_score

候选素材长度与当前还需要填充的 Beat 时长越接近，分数越高。

### quality_score

默认使用 annotation confidence；没有 confidence 时使用 `0.5`。人工确认 `verified=True` 会得到小幅固定加成，但最终不超过 `1.0`。

### continuity_bonus

如果上一段素材与当前候选来自同一个视频，并且源区间不重叠、时间位置相近，会得到最多 `0.03` 的连续性奖励。

V0.1 不假装理解不存在的故事时间关系，只做这一条保守、可解释的连续性信号。

### reuse_penalty

同一个 Segment 被重复使用时：

```text
0.08 / 次
最高 0.20
```

复用会变得更不划算，但**不是绝对禁止**。素材不足时仍然允许复用，从而避免因为“去重规则”导致整条时间轴无法完成。

---

## 6. 时长填充

每个 Beat 的候选检索只执行一次 Top-K，然后 Planner 在候选池中动态重排并填充。

### 长素材

如果候选 Segment 比 Beat 长：

```text
Beat 需要 1200 ms
Segment = 5000..10000 ms
```

V0.1 可以选择：

```text
source_in  = 5000
source_out = 6200
```

只在 canonical Segment 内部裁切。

### 多个短素材

如果一个候选不够长：

```text
400 ms + 500 ms + 300 ms = 1200 ms
```

Planner 会继续选下一候选，直到 Beat 被精确填满。

最终强制：

```text
source_out - source_in
==
timeline_out - timeline_in
```

以及：

```text
第一段 timeline_in == 0
最后一段 timeline_out == NarrationTrack.duration_ms
任意相邻两段：previous.timeline_out == next.timeline_in
```

不允许 destination gap / overlap。

---

## 7. 确定性选择

相同 canonical 输入与相同 PlannerSettings 必须产生相同素材选择顺序。

候选 tie-break 顺序：

1. 更高 total score；
2. 更高 semantic score；
3. 更低历史复用次数；
4. `segment_id` 字符串顺序。

每个 `RoughCutClip.selection_reason` 不是 AI 自由文本，而是固定数值解释，例如：

```text
semantic=0.820; action=0.500; scene=0.000; emotion=0.000;
duration=1.000; quality=0.700; continuity=0.020;
reuse=0.080; total=0.603
```

便于 UI 展示和后续调参审计。

---

## 8. RoughCutPlan 历史

粗剪计划单独保存在：

```text
CLIPATLAS_ROUGHCUT_DB=./data/roughcut/roughcut.sqlite3
```

主要表：

```text
rough_cut_plans
active_rough_cut_plans
```

每次重新生成：

```text
revision 1
revision 2
revision 3
...
```

旧 revision 不删除。

`active_rough_cut_plans` 只保存当前项目正在使用的 plan 指针。

因此用户改旁白、换素材范围或重新粗剪后，旧方案仍可以审计和回看。

---

## 9. API

### 创建 RoughCutPlan

```http
POST /api/v1/rough-cut/plans
Content-Type: application/json
```

示例：

```json
{
  "project_id": "00000000-0000-0000-0000-000000000001",
  "top_k": 12,
  "video_ids": null
}
```

`video_ids` 可选；提供时只从指定视频集合检索。

### 获取当前 active plan

```http
GET /api/v1/rough-cut/plans/active?project_id=<uuid>
```

### 按 ID 获取历史 plan

```http
GET /api/v1/rough-cut/plans/<plan_id>
```

---

## 10. 稳定错误码

### 409 `rough_cut_not_ready`

例如：

- 项目没有 active NarrationTrack；
- active Track 是 TTS `TRACK_ONLY` 或任意 `ESTIMATED`；
- 精确计时模式下句级时间不完整或互相重叠。

### 503 `rough_cut_unavailable`

自动粗剪 runtime 没有配置，例如没有可用语义检索服务。

### 503 `rough_cut_retrieval_failed`

某个 Beat 没有任何可用素材候选。

### 404 `rough_cut_plan_not_found`

查询的 plan 或项目 active plan 不存在。

### 500 `rough_cut_planning_failed`

Planner 生成的时间轴违反内部 canonical invariant。

---

## 11. Runtime 降级

没有配置 Embedding / SemanticSearch 时：

```text
素材库仍能启动
旁白 / TTS 仍能启动
真人旁白导入仍能启动
RoughCutStore 仍能启动
RoughCutPlanner = None
```

此时创建粗剪请求明确返回 `rough_cut_unavailable`，而不是让整个 ClipAtlas 启动失败。

---

## 12. V0.1 明确不做什么

当前 C 阶段不包含：

- OpenTimelineIO 序列化；
- 剪映草稿写入；
- 字幕；
- 转场；
- 特效；
- BGM；
- 自动变速；
- 光流；
- 学习型 reranker；
- LLM Beat 改写；
- 最终视频渲染。

下一阶段固定为：

```text
RoughCutPlan
→ OpenTimelineIO
→ Jianying / 剪映 Adapter
→ 剪映草稿
```

核心 Planner 不依赖剪映格式，避免剪映工程结构反向污染 ClipAtlas canonical 数据。

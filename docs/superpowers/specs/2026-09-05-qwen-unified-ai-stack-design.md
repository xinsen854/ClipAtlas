# ClipAtlas 统一百炼 AI 栈重构设计

日期：2026-09-05

## 目标

将 ClipAtlas 除 TTS 以外的 AI 能力统一到阿里云百炼/千问体系，并把 ASR、OCR、视频向量、视频深度理解作为同一时间轴检索系统的四个数据源。

核心原则：

- 用户只配置一份“阿里云百炼”凭据：API Key + Workspace/Base URL（或地域/Workspace 信息）。
- 软件内部自动派生 OpenAI-compatible 与 DashScope `/api/v1` 端点。
- 软件通过百炼模型列表接口检查当前 Workspace/Key 可用模型，并按固定推荐模型 ID 自动绑定能力；不能仅凭 Key 字符串猜测模型。
- TTS 保持现有独立配置，本次不重构。
- GPT-5.6 从正式视频理解/检索链退出。
- SentrySearch 固定 commit `a89d1282fe52dd98aa71593cda86f8e8b4fbdd3b` 的视频切片、预处理、qwen-cloud 调用、重试/限速核心以 vendored 方式进入 ClipAtlas；只做已通过 PoC 证实必要的 ClipAtlas patch。

## 推荐模型

### 1. 视频/跨模态向量

- 模型：`qwen3-vl-embedding`
- 用途：文本搜视频、视频语义索引、跨模态召回
- 默认向量维度：2560
- 主索引：5 秒 chunk / 1 秒 overlap
- 可选粗索引：30 秒 chunk / 5 秒 overlap
- 1 秒方案彻底取消
- 运行时必须用实际 `len(vector)` 校验维度

### 2. 视频深度理解

- 默认模型：`qwen3.8-flash`
- 用途：Top-K 候选的结构化深度理解，包括人物、动作、场景、物体、情绪、镜头信息、组合语义及文案匹配
- 不再全库阻塞式分析；只对向量/ASR/OCR 召回后的候选做深度分析

### 3. OCR

- 模型：`qwen3.5-ocr`
- 用途：画面精确文字，包括标题、数字、参数、Logo、UI、地名、短暂文字卡
- OCR 抽帧间隔设置保留：关闭 / 1 秒 / 5 秒 / 10 秒；默认 5 秒
- 连续重复文本合并成时间 span

### 4. ASR

ASR 是检索主数据源，不只是字幕导出。

默认第一版推荐：`qwen-audio-3.0-asr-flash`

理由：

- 支持 Base64/URL，适合 ClipAtlas 本地素材经 FFmpeg 抽取音频后直接分段调用，不要求用户额外配置 OSS。
- 单段最长 5 分钟；ClipAtlas 本地将长音频切成 <=5 分钟片段，并把返回时间戳平移回原视频绝对时间轴。
- 支持句级/词级时间戳，可直接用于字幕、关键词检索和粗剪时间定位。
- 支持热词/Prompt 上下文，可用于车型、人名、品牌、专业术语提升识别准确率。

保留后续可选长文件 Provider：`qwen-audio-3.0-asr-flash-filetrans`，但它需要公网可访问文件 URL，因此不作为第一版默认，避免额外引入 OSS 配置。

ASR 产物至少保存：

- source video id
- start_ms
- end_ms
- text
- words[]（如可用）
- model/provider
- revision/status

ASR 结果必须进入检索层。例如查询“越野测试”时，可同时命中：

- qwen3-vl-embedding 画面语义
- ASR 文本中“我们现在开着这个车在越野路上行驶”
- OCR 画面中的“越野篇/越野测试”等文字

## 单一百炼配置

设置页新增/收敛为一个“阿里云百炼”配置组：

- `bailian_api_key`
- `bailian_base_url` 或 `region + workspace_id`

兼容现有已保存字段期间做迁移读取，不立即破坏旧配置。

从 OpenAI-compatible Base URL：

`https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`

自动派生 DashScope API Root：

`https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/api/v1`

用户不需要为视频向量、OCR、ASR、Qwen3.8 分别填写 Key。

## 模型自动识别

“自动识别”不是 API Key 自己知道模型，而是 ClipAtlas 用同一 Key 调百炼模型目录：

`GET {DashScopeApiRoot}/models`

并检查固定推荐模型 ID 是否在当前 Workspace/地域可用：

- `qwen3-vl-embedding`
- `qwen3.8-flash`
- `qwen3.5-ocr`
- `qwen-audio-3.0-asr-flash`

模型目录支持按 model/name/providers/capabilities 等条件查询。UI 显示每项：可用 / 不可用 / 未检测。

如果模型目录存在短时不一致或返回项不足，则对固定模型做最小探测作为二次确认，但不会自动选择 249 个模型中的“名字相似模型”。模型 ID 由 ClipAtlas 推荐表明确指定，避免错误路由。

## 统一检索结构

```text
原视频
  |
  +-- SentrySearch core --> 5s qwen3-vl-embedding ----------+
  |                                                          |
  +-- FFmpeg audio --> Qwen Audio ASR --> timestamp text ----+--> hybrid recall
  |                                                          |        |
  +-- frame extraction --> qwen3.5-ocr --> OCR spans --------+        v
  |                                                               candidate merge/dedupe
  |                                                                    |
  +------------------------------------------------------------ qwen3.8-flash Top-K deep understanding
                                                                       |
                                                                       v
                                                                 rough cut / preview
                                                                       |
                                                                 OTIO / Jianying
```

## 混合召回

第一版不引入复杂学习排序器。三路独立召回：

- visual_score
- asr_score
- ocr_score

先做可解释的规则融合与时间邻接合并；同一事件的重叠 chunk 合并成时间 span，避免粗剪重复选同一个画面。

后续如需要可评估 `qwen3-vl-rerank`，但不列为本次 P0。

## SentrySearch vendoring

固定来源：

- repo: `ssrajadh/sentrysearch`
- commit: `a89d1282fe52dd98aa71593cda86f8e8b4fbdd3b`
- license: Apache-2.0

建议 vendored 路径：

`clipatlas/vendor/sentrysearch/`

核心迁入：

- `base_embedder.py`
- `chunker.py`
- `qwen_cloud_embedder.py`
- `dlq.py`

不迁入：

- CLI
- Tesla/dashcam 专用逻辑
- overlay/highlights
- Gemini
- SentrySearch 自己的 Chroma/store

ClipAtlas patch 仅限已实测确认：

1. 默认主粒度 5s/1s overlap，30s/5s overlap 仅显式粗索引；取消 1 秒。
2. `qwen3-vl-embedding` 维度按当前官方/实际返回 2560 管理并继续实际向量长度校验。
3. 上传前 size gate；不合规时本地 fallback/reencode。
4. Workspace `/api/v1` 适配与单一百炼 Key 注入。
5. still-frame skip 默认关闭（PoC 未节省调用）。
6. 保留 ClipAtlas 自己的 DB/checkpoint/API/UI，不引入 SentrySearch store。

## 数据与兼容边界

- 现有 text-embedding-v4 1024 历史数据不删除；标记为 legacy，不与 qwen3-vl 2560 混库。
- GPT-5.6 配置先做迁移兼容，随后从正式默认链退出；不立即删除历史 annotation/revision。
- Human > AI、revision、OTIO、剪映、TTS、Jianying path safety 均不在本次重构范围内。
- Fake Provider 数据继续隔离，不参加正式检索。

## P0 实施顺序

1. 百炼统一配置模型与模型目录检测。
2. Vendoring SentrySearch 固定 core + attribution。
3. 5 秒 qwen3-vl 主索引替换当前自写 materializer/provider 路径。
4. ASR：FFmpeg 抽音频、<=5min 分段、qwen-audio-3.0-asr-flash、时间戳合并入库。
5. OCR：抽帧、qwen3.5-ocr、重复文本时间 span 合并。
6. Hybrid recall：visual + ASR + OCR + 时间去重合并。
7. qwen3.8-flash Top-K 深度理解，替代 GPT-5.6 正式链。
8. 前端显示百炼模型可用状态、ASR/OCR/视觉索引进度及召回来源。
9. 真实素材黑盒验收后，再删除当前重复的自写视频切片/预处理代码。

## 验收标准

- 用户只填写一份百炼 API Key + Workspace/Base URL，即可检查四类推荐模型是否可用。
- 不要求为 OCR、ASR、视频向量、视频理解分别填写 Key。
- 5 秒视频索引可稳定生成并检索。
- ASR 句子可按关键词召回到正确视频时间段，并能导出字幕时间轴。
- OCR 可召回短标题、数字、UI 等精确文字。
- 同一文案可同时使用视觉、ASR、OCR 三路证据召回素材。
- qwen3.8-flash 只处理 Top-K 候选，不阻塞全库首次可搜索时间。
- 1 秒索引不存在。
- 现有 TTS / OTIO / Jianying / Human revision 功能无回归。

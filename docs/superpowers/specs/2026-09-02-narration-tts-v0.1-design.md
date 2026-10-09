# ClipAtlas Narration / TTS V0.1 设计

## 1. 目标

Narration / TTS V0.1 的目标不是单纯“把文字念出来”，而是建立 ClipAtlas 后续自动剪辑的**声音权威时间轴**。

完整关系：

```text
文案
  ↓
TTS 生成旁白 / 用户导入真人旁白
  ↓
真实音频
  ↓
精确总时长 + 句子/Beat 时间范围 + 可选词级时间码
  ↓
后续 Script Beat Planner
  ↓
素材检索 / 时长适配 / 自动粗剪
```

剪辑层不得使用“文字估算时长”覆盖已经存在的真实音频时长。

---

## 2. 已锁定产品规则

### 2.1 旁白权威来源

项目当前选择哪一种模式，哪一种就是该版本的权威旁白：

- `TTS`：生成后的真实音频是权威。
- `IMPORTED`：用户导入的真实音频是权威。
- `NONE`：仅在没有任何音频时，允许用文字语速估算临时时长。

切换模式不会删除旧版本；旧音频、旧配置和旧时间码必须保留，可回退、审计和比较。

### 2.2 TTS 参数

ClipAtlas 统一抽象以下参数；Provider 不支持的能力由 capabilities 显式声明，UI 自动隐藏或置灰：

- voice / 音色
- gender / 男、女、中性、不限制
- age style / 少年、青年、成熟、老年等标签
- language
- accent
- speed / 语速
- pitch / 音高
- volume / 音量
- emotion / 情绪
- style / 表达风格
- instruction / 自然语言表达指令
- voice cloning / 声音克隆（Provider 支持时）
- voice design / 声音设计（Provider 支持时）
- word timestamps / 词级时间码（Provider 支持时）

### 2.3 随机规则

提供三个随机入口：

1. `RANDOM_VOICE`：只随机符合当前筛选条件的音色。
2. `RANDOM_PARAMETERS`：音色不变，只随机 Provider 支持的可调参数。
3. `RANDOM_ALL`：在用户约束范围内随机音色 + 参数。

默认行为：**一个项目随机一次，然后锁定**。

禁止默认“每一句随机一次”。只有未来明确的多角色配音模式才允许多个 Voice Profile。

所有随机都保存 `random_seed`，同一 seed + 同一 Voice Pool + 同一约束必须得到可复现结果。

---

## 3. 架构边界

```text
NarrationService
   ├── SpeechProvider
   │    ├── DashScopeSpeechProvider        # 第一家真实 Provider
   │    ├── GenericHttpSpeechProvider      # 用户自己的 HTTP API
   │    ├── LocalHttpSpeechProvider        # 本地 CosyVoice / GPT-SoVITS 等
   │    └── FakeSpeechProvider             # 测试
   │
   ├── VoiceSelector
   │    ├── constraints
   │    ├── random seed
   │    └── project lock
   │
   ├── AudioNormalizer
   │    └── FFmpeg → canonical WAV
   │
   ├── NarrationStore
   │    └── SQLite metadata + version history
   │
   └── AlignmentProvider
        ├── provider word timestamps
        ├── imported-audio aligner (future real adapter)
        └── unavailable / track-only status
```

TTS Provider 不允许直接控制 RoughCut；它只返回声音和时间信息。

---

## 4. Provider 合约

### 4.1 `SpeechProviderCapabilities`

建议字段：

```text
preset_voices
voice_metadata
speed_control
pitch_control
volume_control
emotion_control
instruction_control
voice_clone
voice_design
word_timestamps
streaming
languages
```

### 4.2 `SpeechProvider`

最小接口：

```text
name
capabilities
list_voices()
synthesize(request) -> SpeechSynthesisResult
```

`synthesize()` 必须返回：

- provider/model
- audio bytes 或受控临时文件引用
- output format
- sample rate（如果已知）
- duration（如果 Provider 给出；最终仍由 ClipAtlas 对规范化音频重新测量）
- sentence/unit timings（如果 Provider 给出）
- word timings（如果 Provider 给出）
- raw provider metadata

Provider 的 duration/timestamps 是证据；最终 canonical duration 由 ClipAtlas 对落盘后的音频重新测量。

---

## 5. 第一家真实 Provider：DashScope / CosyVoice

V0.1 第一家真实 Provider 采用阿里 DashScope / Model Studio 路线，默认优先使用便宜且参数完整的 Flash 型号。

设计默认值：

```text
provider: dashscope
model: cosyvoice-v3.5-flash
```

但 model 必须可配置，不写死在业务层。

原因：该系列适合直接映射 ClipAtlas 的 `voice / speed / pitch / volume / instruction` 控制，并可扩展系统音色、声音克隆、声音设计和部分时间戳能力。

环境变量示例：

```text
CLIPATLAS_SPEECH_PROVIDER=dashscope
CLIPATLAS_SPEECH_API_KEY=
CLIPATLAS_SPEECH_MODEL=cosyvoice-v3.5-flash
CLIPATLAS_SPEECH_BASE_URL=
CLIPATLAS_SPEECH_WORKSPACE_ID=
```

如果 `CLIPATLAS_SPEECH_API_KEY` 为空，可回退读取 `DASHSCOPE_API_KEY`。

---

## 6. 自定义 API 与本地部署

### 6.1 Generic HTTP Provider

V0.1 不允许用户提交任意可执行代码。

自定义 API 采用受控 HTTP 配置：

```text
endpoint
method
headers/auth
text field mapping
voice field mapping
speed field mapping
pitch field mapping
volume field mapping
audio response mode: bytes / base64 / URL
optional timing response mapping
```

必须设置请求超时、最大响应体、URL scheme 白名单和错误归一化。

### 6.2 Local HTTP Provider

本地部署模型统一通过 HTTP 适配，不让 ClipAtlas 核心直接 shell 执行第三方 TTS 程序。

目标可包括：

- CosyVoice local server
- GPT-SoVITS server
- 其他兼容 HTTP TTS 服务

默认只允许用户配置的 localhost / LAN endpoint；后续 UI 再提供连接测试。

---

## 7. Voice 数据结构

### 7.1 `VoiceDescriptor`

```text
provider
voice_id
display_name
gender
age_style
languages
accents
tags
preview_uri
capability_overrides
```

`gender/age_style/emotion` 是筛选元数据，不假设所有 Provider 都提供官方分类。缺失时允许 `UNKNOWN`。

### 7.2 `SpeechProfile`

```text
id
project_id
provider
model
voice_id
gender_constraint
age_style_constraint
language
accent
speed
pitch
volume
emotion
style
instruction
random_seed
random_mode
locked
created_at
```

`locked=true` 表示该项目后续重新生成旁白时默认复用同一配置，除非用户主动解锁或“换一个”。

---

## 8. Narration 数据结构

### 8.1 `NarrationTrack`

```text
id
project_id
source_mode: TTS | IMPORTED | ESTIMATED
script_hash
speech_profile_id
provider
model
audio_uri
duration_ms
timing_quality
revision
created_at
```

`timing_quality`：

```text
WORD_EXACT
UNIT_EXACT
ALIGNED
TRACK_ONLY
ESTIMATED
```

### 8.2 `NarrationUnit`

```text
id
track_id
sequence
text
start_ms
end_ms
source
```

### 8.3 `NarrationWordTiming`

```text
unit_id
word
start_ms
end_ms
confidence
```

词级时间码可选；句子/Beat 级时间范围是后续自动剪辑的最低要求。

---

## 9. TTS 精确时间策略

对**生成式 TTS**，V0.1 不依赖 Provider 必须返回词级时间戳。

推荐实现：

```text
Script
→ Narration Units（句子/短段）
→ 每个 Unit 单独合成
→ FFmpeg 规范化每段音频
→ 实测每段 duration
→ 按顺序拼接 canonical WAV
→ 累加得到精确 Unit start/end
```

因此即使 Provider 只返回音频，也能得到稳定的句子级真实时间码。

Provider 如果同时返回 word timestamps，则额外保存词级时间码。

这比“整篇一次 TTS 后再猜每句话时长”可靠，也直接服务后面的 Beat 剪辑。

---

## 10. 导入真人旁白

导入音频后：

1. 原始文件只读保存/引用。
2. FFmpeg 规范化为 canonical WAV。
3. ffprobe 取得真实总时长。
4. 如果配置 AlignmentProvider，则生成句子/词级对齐。
5. 如果没有 AlignmentProvider，则状态为 `TRACK_ONLY`。

**重要：** `TRACK_ONLY` 可以试听和保存，但后续自动按 Beat 精确剪辑时必须提示“需要对齐”，不能伪造精确句子时间码。

未来 AlignmentProvider 可接：

- Qwen ASR / 音频模型
- Whisper/faster-whisper
- 本地 forced alignment
- 自定义 API

---

## 11. 音频规范化与存储

ClipAtlas 内部 canonical narration 格式：

```text
WAV / PCM
48 kHz（默认，可配置）
mono 或 stereo 保留策略由 AudioNormalizer 控制
```

目录：

```text
data/
└── narration/
    └── <project_id>/
        └── <track_id>/
            ├── track.wav
            ├── units/
            │   ├── 0001.wav
            │   ├── 0002.wav
            │   └── ...
            └── imported-original.ext   # IMPORTED 模式时可选
```

所有版本不可覆盖旧版本；重新生成产生新 Track revision。

---

## 12. 项目级 Voice 锁定

V0.1 需要一个最小 project identity，用于保存“这个成片项目使用哪个声音”。

不在本阶段构建完整项目管理 UI，只建立稳定的 `project_id` 作为后续 Script / Narration / RoughCut / OTIO 的共同外键。

Voice 随机一次后：

```text
project_id
→ SpeechProfile(random_seed, voice_id, params, locked=true)
→ 后续 regenerate 默认继续使用
```

用户主动点击“换一个”时生成新的 SpeechProfile revision，不覆盖旧 Profile。

---

## 13. API V0.1

建议最小接口：

```text
GET  /api/v1/speech/providers
GET  /api/v1/speech/providers/{provider}/voices
POST /api/v1/speech/profiles/randomize
POST /api/v1/narration/tts
POST /api/v1/narration/import
GET  /api/v1/narration/{track_id}
POST /api/v1/narration/{track_id}/activate
```

后续 UI 可直接围绕这些接口做声音面板和试听。

---

## 14. 错误与重试

TTS 失败必须按 Unit 持久 checkpoint。

示例：

```text
Unit 1 生成成功 → 保存
Unit 2 生成成功 → 保存
Unit 3 API 429 → FAILED

Retry
→ 跳过 Unit 1/2
→ 从 Unit 3 继续
```

禁止一个 5 分钟旁白最后一句失败后重新付费生成前面全部内容。

错误类型统一：

```text
SpeechAuthenticationError
SpeechRateLimitError
SpeechRequestError
SpeechConfigurationError
SpeechAudioValidationError
```

---

## 15. 与后续自动剪辑的硬接口

后续 RoughCut Planner 不直接读取某家 TTS Provider。

唯一输入是 canonical：

```text
NarrationTrack
NarrationUnit[]
NarrationWordTiming[] (optional)
```

后续主链：

```text
NarrationUnit.start_ms/end_ms
        ↓
Script Beat 时间窗口
        ↓
Semantic Retrieval Top-K
        ↓
动作/情绪/时长/连续性/重复度 rerank
        ↓
source_uri + source_start_ms/source_end_ms
        ↓
RoughCutPlan
        ↓
OpenTimelineIO
        ↓
Jianying Adapter
        ↓
剪映草稿
```

**旁白时间控制成片时长；素材只在这个时间窗口里适配，不反过来随意拉长旁白。**

---

## 16. 测试策略

TDD 必须覆盖：

1. Voice capability 映射。
2. 男/女/年龄/语言筛选随机只在合格 Voice Pool 内发生。
3. random seed 可复现。
4. project-level lock 不会每句随机。
5. Provider 不支持的 speed/pitch/emotion 不会偷偷发送。
6. Unit 分段 TTS 后 canonical duration 累加正确。
7. 音频规范化失败不产生假成功 Track。
8. Unit checkpoint 可断点续作。
9. 旧 Track / Profile revision 不被覆盖。
10. imported narration 真实总时长由本地媒体探测确定。
11. 没 aligner 时 imported track 明确为 `TRACK_ONLY`。
12. Generic HTTP / Local HTTP 的 URL、超时、响应大小和错误归一化。
13. DashScope Provider 的参数映射和错误归一化。
14. API validation / 404 / 409 / 503。

---

## 17. 本阶段不做

Narration / TTS V0.1 不包含：

- 文案语义 Beat 拆解算法
- Top-K 素材 rerank
- 自动决定镜头数量
- 转场/速度变化/字幕排版
- OpenTimelineIO 输出
- 剪映草稿写入
- 多角色自动配音调度
- 完整前端 UI

这些属于后续独立阶段；本阶段只保证它们获得稳定、真实、可版本化的声音时间轴。

---

## 18. 验收定义

Narration / TTS V0.1 完成时，必须能够：

```text
输入一段文案
→ 选择或随机一个符合条件的声音
→ 项目级锁定声音和参数
→ 调用真实/假 SpeechProvider 逐 Unit 生成
→ 失败可从缺失 Unit 继续
→ 规范化并拼成一个 canonical narration WAV
→ 得到真实总 duration_ms
→ 得到每个 NarrationUnit 的真实 start_ms/end_ms
→ 保存版本历史
→ 后续 RoughCut Planner 可直接消费
```

导入真人旁白必须至少能得到真实总时长，并对“是否具备 Beat 级精确时间码”给出真实状态，禁止伪造精度。

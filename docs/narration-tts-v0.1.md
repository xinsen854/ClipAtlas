# ClipAtlas Narration / TTS V0.1

## 1. 这一版解决什么问题

Narration / TTS V0.1 的目标不是单独做一个“文字转语音工具”，而是建立 ClipAtlas 自动剪辑后续使用的**真实声音时间尺**。

当前已经形成两条主链：

```text
本地视频
→ 扫描 / 镜头切分 / 抽帧
→ AI 语义理解
→ 人工修正
→ Embedding
→ 可搜索素材库
```

以及：

```text
文案
→ TTS 旁白 / 导入真人旁白
→ 规范化真实音频
→ 实测总时长
→ NarrationUnit 时间窗口
→ Active NarrationTrack
```

当前粗剪链已经把这两条链连接起来：

```text
NarrationUnit / Active NarrationTrack
→ Script Beat
→ Top-K 素材召回
→ 动作 / 情绪 / 时长 / 连续性 / 重复度 rerank
→ RoughCutPlan
→ OpenTimelineIO
→ 剪映 Adapter
→ 剪映草稿
```

**只要真实旁白存在，真实音频时长就是剪辑时间轴权威。** 后续 Planner 不允许用字数估算覆盖真实旁白时长。

---

## 2. 声音配置与随机规则

统一的 `SpeechProfile` 支持：

- Provider / Model；
- Voice ID；
- 男声、女声、中性、不限制等筛选条件；
- 年龄感筛选；
- 语言、口音；
- 语速；
- 音高；
- 音量；
- 情绪 / 风格 / instruction；
- random seed；
- random mode；
- project-level lock。

随机模式：

```text
RANDOM_VOICE       只换音色
RANDOM_PARAMETERS  只随机 Provider 支持的参数
RANDOM_ALL         音色 + 参数一起随机
NONE               不随机
```

默认产品规则是：**一个项目随机一次，然后锁定。** 不会默认每句话换一个声音。

相同 seed + 相同 Voice Pool + 相同约束会得到可复现的结果。

Provider 不支持的控制参数不会偷偷发送给 Provider。

---

## 3. 已实现的 Speech Provider

### 3.1 FakeSpeechProvider

用于 CI、本地开发和不消耗真实 API 费用的黑盒测试。

它输出真实 WAV 字节，因此可以验证声音链路，而不依赖第三方服务。

### 3.2 DashScopeSpeechProvider

第一家真实 TTS Adapter，默认模型：

```text
cosyvoice-v3.5-flash
```

当前非流式 HTTP Adapter 支持：

- voice ID；
- speed；
- pitch；
- volume；
- language hints；
- instruction；
- HTTP 认证 / 限流 / 网络 / 返回结构错误归一化；
- 服务返回音频 URL 后的受控下载。

当前 Adapter 明确声明：

```text
word_timestamps = false
streaming = false
```

不会把尚未实现的能力伪装为已支持。

### 3.3 GenericHttpSpeechProvider

为用户自己的 TTS API 提供受控 HTTP Adapter。

支持：

- endpoint；
- method；
- headers；
- 声明式字段映射；
- bytes / base64 / URL 三种明确返回模式；
- timeout；
- 最大响应字节；
- HTTP 错误归一化。

不支持 `eval`、脚本模板执行或任意 shell。

### 3.4 LocalHttpSpeechProvider

用于本地部署的 CosyVoice、GPT-SoVITS 或其他 HTTP TTS Server。

V0.1 安全策略更保守：默认只允许回环地址：

```text
localhost
127.0.0.0/8
::1
```

因此核心不会因为一个“本地 TTS 配置”意外请求公网或局域网其他机器。

Generic / Local HTTP Adapter 已作为代码级 Provider 能力实现；后续 UI 可以增加可视化 Provider 配置保存与连接测试，不需要修改 Narration / RoughCut 核心合约。

---

## 4. TTS 的真实时间策略

ClipAtlas 不采用“整篇文字按字数猜每句时长”。

TTS 流程是：

```text
Script
→ deterministic Narration Units
→ Unit 0 单独合成
→ Unit 1 单独合成
→ ...
→ 每段落盘
→ FFmpeg 规范化
→ ffprobe 实测每段 duration
→ 拼接 canonical track
→ 再实测最终 Track duration
```

因此即使某家 Provider 只返回音频、不返回时间戳，也可以得到真实 Unit 时间窗口。

例如：

```text
Unit 0  0 ───── 1200 ms
Unit 1  1200 ── 2000 ms
Unit 2  2000 ── 3500 ms
Track            3500 ms
```

后续 RoughCut 的时间窗直接使用这些整数毫秒。

---

## 5. 失败断点续作

长旁白不会因为末尾一次 API 失败而全部重做。

示例：

```text
Unit 1 成功 → 保存音频 + checkpoint
Unit 2 成功 → 保存音频 + checkpoint
Unit 3 成功 → 保存音频 + checkpoint
Unit 4 API 429 → 本次 Track 未完成

Retry
→ 找回同一个未完成 Track
→ 校验 Unit 1/2/3 checkpoint 与落盘音频
→ 跳过 Unit 1/2/3
→ 从 Unit 4 继续
```

未完成 Track 由：

```text
project_id + script_hash + speech_profile_id
```

恢复。

完整 Track 成功以后，再主动重新生成同一文案，则产生新的 Track revision，不覆盖旧版本。

---

## 6. 真人旁白导入

导入真人旁白后：

```text
原始音频
→ ClipAtlas 受控目录
→ FFmpeg 规范化
→ ffprobe 实测真实总时长
```

如果没有 AlignmentProvider：

```text
TimingQuality = TRACK_ONLY
```

这意味着：

- 总音频时长是真的；
- 可以保存、播放、设为 Active Track；
- 不会伪造每句话 start/end；
- 自动粗剪可以把完整旁白作为 **1 个覆盖整条真实音频时长的低精度 Beat** 使用；
- 若要句级或词级的精细素材匹配，仍需要 ASR / forced alignment 补时间码。

如果存在合格 AlignmentProvider，则可升级为：

```text
TimingQuality = ALIGNED
```

对齐结果必须单调、不重叠、不超出真实 Track duration，否则拒绝激活。

---

## 7. FFmpeg 边界

当前开发版**没有把 FFmpeg 二进制安装进 Python 包或 Git 仓库**。

`AudioNormalizer` 和视频准备模块通过命令执行器调用系统：

```text
ffmpeg
ffprobe
```

所以真实媒体处理时，开发机器当前需要让二者位于 `PATH`。

自动测试中的 NarrationService 使用可替换的 fake/stub audio normalizer，不会因为 GitHub Runner 恰好装有 FFmpeg 而产生“假绿”。

正式桌面分发时建议：

```text
ClipAtlas 安装包
→ 捆绑受控版本 ffmpeg / ffprobe
→ 程序优先解析应用自己的 binary path
→ 启动时 health check
→ 普通用户不需要手动配置 PATH
```

FFmpeg 二进制不应直接提交进源代码仓库。

---

## 8. 数据与版本历史

SQLite 中持久化：

```text
SpeechProfile revisions
NarrationTrack revisions
NarrationUnit checkpoints
NarrationWordTiming
Active NarrationTrack
```

旧 Profile、旧 Track、旧 Unit 版本不会因为重新生成被无声覆盖。

Active Track 只是项目当前选择的权威版本，不等于删除其他版本。

---

## 9. API

当前已暴露：

```text
GET  /api/v1/speech/providers
GET  /api/v1/speech/providers/{provider}/voices
POST /api/v1/speech/profiles/randomize
POST /api/v1/narration/tts
POST /api/v1/narration/import
GET  /api/v1/narration/{track_id}
POST /api/v1/narration/{track_id}/activate
```

真人旁白上传使用 ClipAtlas 的受控临时目录，并设置上传体积上限；传给 importer 后临时文件会清理。

---

## 10. 环境变量

```text
CLIPATLAS_NARRATION_ROOT=./data/narration
CLIPATLAS_ENABLE_FAKE_SPEECH_PROVIDER=false
CLIPATLAS_SPEECH_PROVIDER=
CLIPATLAS_SPEECH_API_KEY=
CLIPATLAS_SPEECH_BASE_URL=https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer
CLIPATLAS_SPEECH_MODEL=cosyvoice-v3.5-flash
DASHSCOPE_API_KEY=
```

`CLIPATLAS_SPEECH_API_KEY` 为空时可以回退到 `DASHSCOPE_API_KEY`。

没有任何 TTS Provider 时，应用仍可启动，真人旁白导入仍然可用；TTS 生成接口会明确返回“未配置”，而不是让整个 ClipAtlas 无法启动。

---

## 11. 给 RoughCut 的硬交接契约

Script Beat / RoughCut Planner 不允许直接依赖 DashScope、Fake、Generic HTTP 或任何其他 TTS 厂商。

只能消费 canonical：

```text
Active NarrationTrack
NarrationUnit[]
NarrationWordTiming[]  # optional
```

对于 `UNIT_EXACT / WORD_EXACT / ALIGNED`：

```text
第一个 Unit.start_ms == 0
相邻 Unit 必须连续
最后一个 Unit.end_ms == NarrationTrack.duration_ms
```

对于 `IMPORTED + TRACK_ONLY`：

```text
NarrationTrack.duration_ms 必须是真实实测总时长
NarrationUnit.start_ms / end_ms 保持为空
RoughCut 只允许生成 1 个整轨低精度 Beat
```

粗剪主链：

```text
NarrationUnit.start_ms/end_ms 或 imported Track 真实总时长
→ Script Beat 时间窗
→ Semantic Retrieval Top-K
→ rerank
→ source_uri + source_start_ms/source_end_ms
→ RoughCutPlan
→ OTIO
→ 剪映 Adapter
```

素材适应旁白时间窗，不能反过来随意把已经存在的旁白拉长。

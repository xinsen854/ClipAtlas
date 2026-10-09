# OTIO → 剪映导出 V0.1

ClipAtlas 的导出层现在固定为：

```text
RoughCutPlan
→ OpenTimelineIO (OTIO)
→ Jianying Adapter
→ 可编辑剪映草稿目录
```

这一层只消费已经持久化的 `RoughCutPlan` 与它引用的历史 `NarrationTrack`。导出失败不会重新运行视频理解、Embedding、语义检索、TTS 或 RoughCutPlanner。

## 1. 时间权威

ClipAtlas 核心时间单位仍是整数毫秒。

OTIO 使用固定：

```text
rate = 1000
1 OTIO value = 1 ms
```

因此：

```text
source_in_ms / source_out_ms
→ OTIO source_range
→ 剪映 source_timerange（微秒）
```

剪映 Adapter 使用精确整数换算：

```text
start_us = start_ms × 1000
duration_us = duration_ms × 1000
```

不使用浮点秒作为 canonical 时间。

旁白仍然控制最终目标时间轴：

> 视频素材适配真实旁白时长，而不是先确定视频长度再强行拉伸或压缩旁白。

## 2. OTIO 内容

每个导出的 `.otio` 包含：

- 1 条主视频轨；
- 1 条旁白音轨；
- `plan_id`；
- `project_id`；
- `narration_track_id`；
- RoughCut revision；
- Narration revision；
- 总时长；
- 每个视频片段的精确 source range；
- 每个片段对应的 ClipAtlas metadata。

导出时读取的是 `RoughCutPlan` 明确引用的历史 `NarrationTrack`，不是当前 active narration。这样旧版粗剪可以稳定重现，不会被后来重新生成的旁白覆盖。

## 3. 剪映 portable 模式

当前已经自动验证的路径是：

```text
OTIO
→ pyJianYingDraft 0.3.x
→ draft_content.json 等草稿文件
```

V0.1 创建：

- `main_video` 视频轨；
- `narration` 旁白轨。

保持：

- OTIO 视频顺序；
- 原素材路径；
- source in/out；
- destination timeline；
- 旁白从 0 开始；
- 旁白覆盖完整总时长。

V0.1 **不会自动添加**：

- BGM；
- 转场；
- 特效；
- 调色；
- 变速；
- 光流；
- 字幕。

## 4. 本地媒体限制

剪映 Adapter V0.1 只接受本地媒体：

```text
file:///...
本地文件路径
```

HTTP、S3 或其他云端 URI 不会被静默下载，而是明确返回不支持的媒体错误。

## 5. Jianying Pro 10.8

配置中保留：

```text
CLIPATLAS_JIANYING_MODE=jianying_pro_10_8
CLIPATLAS_JIANYING_INSTALL_DIR=
CLIPATLAS_JIANYING_USER_DATA=
```

`jianying_pro_10_8` 模式要求显式本地安装路径和用户数据路径。缺少这些路径时，只禁用剪映导出，不影响 OTIO 导出和 ClipAtlas 其他功能。

当前 CI 能验证的是草稿数据生成与配置隔离，**不能代替 Windows 上剪映 Pro 10.8 客户端真实打开草稿的实机验收**。因此 V0.1 不宣称 CI 已验证客户端兼容性。

## 6. 可选依赖

核心 ClipAtlas 不依赖剪映库即可启动。

需要剪映 portable 导出时安装：

```bash
pip install -e ".[jianying]"
```

开发环境：

```bash
pip install -e ".[dev]"
```

`dev` 已包含测试过的 `pyJianYingDraft 0.3.x`。

缺少可选依赖时：

- ClipAtlas 可以启动；
- OTIO 可以导出；
- 剪映 backend 标记为 unavailable。

## 7. 环境变量

```text
CLIPATLAS_EXPORT_ROOT=./data/exports
CLIPATLAS_JIANYING_DRAFT_ROOT=
CLIPATLAS_JIANYING_INSTALL_DIR=
CLIPATLAS_JIANYING_USER_DATA=
CLIPATLAS_JIANYING_MODE=portable
```

说明：

- `CLIPATLAS_EXPORT_ROOT`：`.otio` 输出根目录；
- `CLIPATLAS_JIANYING_DRAFT_ROOT`：剪映草稿根目录；
- `CLIPATLAS_JIANYING_MODE`：当前可使用 `portable`，并保留 `jianying_pro_10_8` 配置模式；
- 安装目录和用户数据目录仅用于本地剪映模式，不允许普通 API 请求任意指定文件系统位置。

## 8. API

### 导出 OTIO

```http
POST /api/v1/exports/otio
```

请求：

```json
{
  "plan_id": "00000000-0000-0000-0000-000000000001"
}
```

返回 `OtioExportArtifact`，包括实际 `.otio` 路径和 revision / duration 信息。

### 导出剪映草稿

```http
POST /api/v1/exports/jianying
```

请求：

```json
{
  "plan_id": "00000000-0000-0000-0000-000000000001",
  "draft_name": "ClipAtlas Rough Cut",
  "width": 1920,
  "height": 1080
}
```

草稿根目录、剪映安装路径等由本机环境配置控制，不从普通请求中传入。

## 9. 稳定错误码

```text
404 export_plan_not_found
409 export_not_ready
500 export_invariant_failed
500 otio_serialization_failed
503 jianying_unavailable
503 jianying_dependency_missing
409 jianying_not_configured
422 jianying_media_unsupported
500 jianying_write_failed
```

## 10. 失败隔离

导出层不会修改：

- `RoughCutPlan`；
- `NarrationTrack`；
- 语义索引；
- 已经生成的 `.otio` 文件。

剪映草稿写入失败后可以直接重试，不需要重新运行检索、TTS 或自动粗剪。

## 11. V0.1 明确不做

V0.1 不负责：

- 自动启动剪映 GUI；
- 自动点击/控制剪映；
- 最终视频渲染；
- 字幕；
- BGM；
- 转场和特效；
- 调色；
- 云端素材自动下载。

当前目标只有一个：

> 把已经确定的 RoughCutPlan 无损地变成可复用 OTIO，并提供一个可替换的剪映草稿导出边界。

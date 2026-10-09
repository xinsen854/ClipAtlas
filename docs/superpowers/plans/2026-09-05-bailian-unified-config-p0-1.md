# P0-1｜统一百炼配置 + 四模型自动检测实施计划

## 范围

只实现 `docs/superpowers/specs/2026-09-05-qwen-unified-ai-stack-design.md` 中的 P0-1。

本阶段不修改 SentrySearch、ASR、OCR 实现、Hybrid Recall、粗剪算法或 TTS/Speech Profile。

## Task 1｜RED：锁定百炼设置与安全迁移

修改测试：

- `tests/settings/test_settings_store.py`
- `tests/settings/test_settings_probe.py`
- `tests/api/test_settings.py`
- `frontend/src/features/settings/SettingsPage.test.tsx`

测试必须覆盖：

1. 单一 `bailian_api_key` / `bailian_base_url`，密钥不回显。
2. 阿里云 `embedding_base_url` 可作为旧配置迁移候选。
3. 第三方 `qwen_base_url` 不得自动迁入百炼。
4. 一个 Base URL 自动派生 OpenAI-compatible 与 DashScope API Root。
5. 只精确检测四个固定模型 ID，不做模糊替换。
6. 前端只显示一个“阿里云百炼”非 TTS 配置区，并保留独立“语音服务”。

先提交测试并确认 CI 为 RED。

## Task 2｜GREEN：后端最小实现

修改：

- `clipatlas/settings/models.py`
- `clipatlas/settings/store.py`
- `clipatlas/settings/probe.py`
- `clipatlas/api/routes/settings.py`
- 必要时 `clipatlas/settings/__init__.py`

实现：

- 百炼配置字段、clear flag、环境变量。
- 仅对可信阿里云 URL 做旧 embedding 配置兼容迁移。
- URL 派生与固定模型状态检测。
- 新百炼模型检测 API，不返回密钥。
- 保留旧 Qwen/Embedding 字段用于历史兼容，不删除旧数据。

## Task 3｜GREEN：运行时兼容注入

修改：

- `clipatlas/settings/store.py`
- `clipatlas/app_state.py`（仅在确有必要时）
- `.env.example`

目标：保存新的百炼配置后，现有 Qwen / Embedding runtime 能通过兼容环境变量继续工作；第三方旧 Qwen 配置不能被误当作百炼配置；TTS 注入逻辑保持不变。

## Task 4｜GREEN：前端统一配置卡

修改：

- `frontend/src/api/settings.ts`
- `frontend/src/features/settings/SettingsPage.tsx`
- 对应测试

目标：

- 单一“阿里云百炼”卡：API Key + Workspace/Base URL + “检查模型”。
- 固定显示 `qwen3-vl-embedding`、`qwen3.8-flash`、`qwen3.5-ocr`、`qwen-audio-3.0-asr-flash` 状态。
- 不再让用户分别填写视频理解 Key / 语义索引 Key。
- 语音/TTS 区域保持现状。

## Task 5｜验证与反向 diff

依次确认：

- Ruff
- Mypy
- Pytest
- Frontend Tests
- Typecheck
- Build

CI 全绿后检查与起点 `5273b3e87ba3b5a99a2fbba7a6cacb5c713b01e6` 的 diff，重点排查：

- 是否修改了 P0-1 之外模块。
- 是否存在旧 UI/旧 runtime 绕过统一百炼配置。
- 是否错误删除 legacy 设置或历史数据。
- 是否误动 TTS。

全部通过后再将隔离分支快进回 `feat/video-index-profiles-v0.1-active`；本阶段到此停止，不进入 P0-2。

# ClipAtlas Runtime UX Polish Design

## Goal

Polish ClipAtlas for real-machine use without changing its product boundary: keep provider choice vendor-neutral, make service configuration verifiable, make material parsing controllable per item, and improve desktop layout/readability.

## Scope

This design covers four areas only:

1. Desktop shell layout and visual theme.
2. Settings service usability and provider verification.
3. Library parsing terminology and per-item parse/reparse controls.
4. Small guidance copy for TTS and Jianying configuration.

It must not alter RoughCut scoring/matching logic, OTIO/Jianying export core, semantic ranking math, Human > AI precedence, or turn ClipAtlas into a browser editor.

## 1. Desktop shell

- The left sidebar containing ClipAtlas branding and the six primary navigation items is fixed for the full viewport height.
- Vertical scrolling happens only in the right content pane.
- The right header remains part of the right-hand shell and does not cause the left sidebar to move.
- Preserve exactly six navigation items: 工作台 / 素材库 / 素材搜索 / 文案与旁白 / 自动粗剪 / 设置.

### Theme

Use a restrained professional warm palette rather than saturated white/orange/red blocks:

- Warm off-white / ivory page background.
- Charcoal primary text.
- Amber-orange as the main interactive accent.
- Vermilion/red only for destructive/error/important alert semantics.
- Form controls remain white for readability.
- Success and error semantic colors remain visually distinct from decorative section colors.

No gradients or large saturated red surfaces.

## 2. Settings service sections

Each service remains provider-neutral and user-editable.

### Visual grouping

Settings cards use subtle full-card tinted backgrounds and borders:

- 视频理解服务: warm light orange.
- 语义索引服务: light muted violet.
- 语音服务: light cyan/blue-gray.
- 剪映: warm light gray.

Inputs remain white.

### Terminology and guidance

- Explain Embedding in Chinese as `语义向量模型（用于按意思搜索素材）` while retaining the technical term where useful.
- Model guidance is recommendation-only, never validation or vendor lock-in. A recommendation may be rendered as muted helper text such as `推荐：Chameleon 3` when product copy is configured for that field.
- Jianying install directory helper text must say it accepts a directory only.
- Jianying executable helper text must say it accepts the `.exe` path only and no launch arguments.
- User data directory copy must state when it is required.

### Test connection

Video understanding, semantic embedding, and TTS each get a `测试连接` action.

Rules:

- Test the current unsaved form values, including newly typed API Key, Base URL, provider, and model.
- The browser never sends the secret directly to a third-party vendor. The form sends it only to the local ClipAtlas backend test endpoint; the backend performs the upstream probe.
- The test action must not persist the supplied secret or mutate current settings.
- Normalize user-visible outcomes at least for success, authentication/authorization failure, 404 or incompatible endpoint, 429/rate limit, timeout/network failure, invalid/unavailable model, and other upstream failure.
- A failed test must not clear or overwrite the form.

### Fetch models

- Offer `获取模型` only as an enhancement where a configured provider/protocol can list models.
- Failure or protocol incompatibility must leave manual model entry available.
- Do not require a vendor-specific models endpoint for custom providers.

## 3. Library terminology

User-facing library copy changes from generic `处理` to `解析` where it refers to media ingestion/AI analysis state:

- 处理状态 -> 解析状态
- 等待处理 -> 等待解析
- 处理中 -> 解析中
- 处理完成 -> 解析完成
- 处理失败 -> 解析失败
- retry action copy -> 重新解析 where applicable

Internal enum names may remain unchanged to avoid unnecessary schema churn.

## 4. Per-item parsing controls

### Single-item parse

For an item in the queued/waiting state, expose `单条解析`.

- It explicitly targets that item instead of relying on queue ordering.
- It is allowed even when global parsing is paused.
- While a single-item parse runs, the same item cannot be started again.
- After it completes, global pause remains unchanged. If global parsing was paused, it stays paused and no next item is automatically consumed.

### Reparse

For completed and failed items expose `重新解析`.

Default reparse semantics:

- Reuse the existing prepared-media checkpoint when valid.
- Do not rerun ffprobe / scene detection / frame extraction merely to refresh AI semantics.
- Force a new video-understanding analysis for every existing segment.
- Save new AI annotations as new revisions/history rather than deleting prior records.
- Re-run embedding for the resulting effective annotation.
- If prepared-media checkpoint/catalog data is unavailable or invalid, safely fall back to full local preparation.

### Human annotation precedence

Human > AI remains absolute.

- Reparse may create a newer AI revision, including replacement of historical Fake Provider output.
- Existing Human annotations remain the effective annotation.
- Re-embedding after reparse must continue to index the effective Human annotation for segments with Human overrides; AI reparse must not silently make AI effective over Human.

## 5. Global pause relationship

- Global pause stops automatic sequential queue consumption.
- It does not prohibit explicit `单条解析` / `重新解析` commands from the user.
- An explicit item action processes only the requested item and does not implicitly resume the automatic supervisor.

## 6. TTS guidance

Keep service connection settings centralized under Settings and voice/profile controls under 文案与旁白.

- Do not duplicate API Key storage in the narration page.
- When TTS is unavailable, provide a clear route/copy directing the user to configure the speech service in Settings.
- Users may continue to upload human narration regardless of TTS provider availability.

## 7. Provider neutrality

Using Alibaba Cloud for current real-machine testing does not change the product architecture.

- Base URLs, provider identifiers, API keys and model names remain configurable.
- Recommendations/defaults are not hard validation rules.
- Custom or alternative providers remain possible through existing provider interfaces.

## 8. Security and persistence boundaries

- Connection-test secrets are one-shot request data and are not logged or persisted by the test action.
- No browser-controlled shell command, arbitrary executable arguments, or arbitrary Jianying launch arguments are added.
- Reparse endpoints accept library item identifiers, not arbitrary filesystem paths.

## 9. Verification

Implement in isolated, reviewable batches:

A. Fixed sidebar + global theme.
B. Settings visual grouping, copy, test connection and optional model retrieval.
C. Backend single-item parse/reparse semantics.
D. Library UI terminology/actions and TTS/Jianying guidance.

Every behavior change follows RED -> minimal GREEN -> full Python/frontend CI -> diff review before the next batch.

For every batch verify:

- Is the change required by this design?
- Is there any unrelated refactor or invented capability?
- Can the behavior be bypassed in a way that violates the design?
- Did the change over-restrict provider choice or user workflows?

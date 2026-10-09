# Index Progress + Hybrid Recall UI P0-8 Design

Date: 2026-09-05

## Goal

Expose the already-existing visual/ASR/OCR indexing state in the material detail UI and make Hybrid Recall the primary material-search surface, without creating another progress persistence system.

## Scope

P0-8 contains only two product changes:

1. Material detail shows Visual / ASR / OCR indexing progress.
2. Material search can query `/api/v1/search/hybrid` and displays recall-source provenance.

The Bailian four-model availability UI is already implemented in Settings and is not modified in P0-8.

## Progress architecture

Add one read-only `LibraryIndexProgressReader` over the existing `library.sqlite3` tables. It performs `SELECT` only and creates no tables.

Sources:

- Visual: `catalog_video_chunk_checkpoints`, fixed current `qwen-vl-video` + `qwen3-vl-embedding` + 5s/1s profile.
- ASR: `catalog_asr_chunks`, fixed `bailian-asr` + `qwen-audio-3.0-asr-flash`, latest revision only.
- OCR: `catalog_ocr_samples`, fixed `bailian-ocr` + `qwen3.5-ocr`, latest revision for the currently configured OCR interval only.

Expected totals are derived from existing chunk semantics, not persisted:

- Visual total: `plan_video_chunks(duration_ms, 5000, 1000)`.
- ASR total: `ceil(duration_ms / MAX_ASR_CHUNK_DURATION_MS)` when audio is present.
- OCR total: `ceil(duration_ms / configured_interval_ms)`.

Each source exposes only:

- `enabled`
- `applicable`
- `completed`
- `processing`
- `failed`
- `total`

No percentage is stored; UI derives it.

`applicable=false` is used for ASR when the video has no audio. `enabled=false` means that indexer is not configured in the current runtime.

## API

Add:

`GET /api/v1/videos/{video_id}/index-progress`

Response:

```json
{
  "visual": {"enabled": true, "applicable": true, "completed": 20, "processing": 1, "failed": 0, "total": 100},
  "asr": {"enabled": true, "applicable": true, "completed": 1, "processing": 0, "failed": 0, "total": 2},
  "ocr": {"enabled": true, "applicable": true, "completed": 50, "processing": 0, "failed": 0, "total": 100}
}
```

The endpoint is read-only and uses the same video 404 behavior as existing video detail endpoints.

## Frontend material detail

`LibraryItemPage` reads index progress when `video_id` exists. It shows three compact rows:

- 视频向量 · 5 秒
- ASR
- OCR

Display rules:

- disabled -> `未启用`
- not applicable -> `无音轨` for ASR
- otherwise -> `completed / total`, progress bar, plus processing/failed counts when non-zero.

Do not add polling in P0-8. Existing page refresh/refetch is enough until real user testing proves live polling is needed.

## Frontend search

Add `HybridSearchHit` and `searchHybrid()` to the existing search API client.

Search page changes:

- default mode becomes `hybrid`;
- keep 5s vector, 30s vector, and legacy semantic modes as explicit alternatives;
- hybrid result card shows merged time span and final score;
- show source tags only for sources actually present: `视觉`, `ASR`, `OCR`;
- show per-source scores when present;
- show matched ASR/OCR text snippets when present.

Do not expose DeepPass as a search mode. DeepPass remains internal to RoughCut.

## Anti-overengineering constraints

Do not add:

- progress tables;
- WebSocket/SSE progress events;
- polling timers;
- background jobs;
- a frontend state store for progress;
- duplicate Bailian model-status UI;
- DeepPass UI/API;
- new retrieval scoring logic;
- changes to indexing execution.

## Verification

Targeted tests must prove:

- reader counts existing visual checkpoints correctly;
- ASR/OCR use latest revision only;
- disabled and no-audio states are distinct;
- progress API returns the reader result and preserves video 404;
- search client calls `/search/hybrid` with existing query semantics;
- SearchPage defaults to Hybrid and renders provenance;
- LibraryItemPage renders the three source-progress states;
- existing search modes remain available.

Full Ruff/Mypy/Pytest/frontend verification remains required before merge. Zero-step Actions is recorded as infrastructure-blocked, not treated as product-code failure.

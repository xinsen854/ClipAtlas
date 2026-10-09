# P0-4 Qwen Audio ASR Implementation Plan

Date: `2026-09-05`
Base: `4fa0485795b4df72d8f56092d788a0d5229cc0c2`
Branch: `feat/qwen-audio-asr-p0-4`

## Scope

Implement only the ASR stage from the locked unified Bailian design:

- local video audio -> deterministic FFmpeg chunks
- `qwen-audio-3.0-asr-flash` over Bailian HTTP
- sentence/word timestamps from SSE when available
- ordinary JSON fallback for short audio responses
- shift chunk-relative timestamps onto the source-video absolute timeline
- resumable persistence in the existing library SQLite file
- run ASR inside the existing sequential library worker

Do not implement OCR, Hybrid Recall, qwen3.8 Top-K changes, new UI, filetrans/OSS, speaker diarization, subtitle export, a second queue, or a second database.

## API facts / chunk policy

Current Bailian behavior constrains the implementation:

- use HTTP rather than DashScope SDK globals
- synchronous audio is limited to at most five minutes
- Base64 input is bounded by the API's 10 MB encoded-input limit
- `sample_rate` is numeric `16000`
- `X-DashScope-SSE: enable` returns SSE only when the audio is at least one minute; shorter audio can return ordinary JSON
- final sentence/word timestamps are identified by `sentence_end=true`

ClipAtlas therefore materializes mono 16 kHz PCM16 WAV chunks with a maximum duration of **225 seconds**. At this deterministic bitrate the Base64 payload remains below 10 MB with useful headroom while requiring fewer requests than the initial 180-second proposal. The provider still enforces the actual encoded-size gate before every request.

Successful temporary WAV chunks are removed after their transcript is durably stored. A failed chunk remains in cache so the next retry can reuse it.

## Minimal architecture

### `clipatlas/asr/models.py`

Own only the ASR data contracts:

- `ASRWord`
- `ASRSentence`
- `ASRAudioChunk`
- `ASRChunkStatus`
- `ASRChunkRecord`

A chunk record contains provenance, revision/status/attempts/error, absolute source-video span, and sentence/word timestamp payload.

### `clipatlas/asr/audio.py`

`ASRAudioChunkMaterializer` reuses the existing generic `AsyncCommandRunner` and FFmpeg. It creates deterministic bounded mono 16 kHz PCM16 chunks and reuses an existing non-empty failed chunk.

It does not reuse `speech.AudioNormalizer`; that module owns narration/TTS-specific errors and semantics.

### `clipatlas/asr/qwen.py`

`QwenAudioASRProvider`:

- POSTs to `{dashscope_api_root}/services/aigc/multimodal-generation/generation`
- uses the formal Bailian Bearer key
- requests SSE but accepts either SSE or ordinary JSON responses
- sends Base64 WAV data
- keeps only sentence-final results
- validates sentence/word timestamps
- normalizes auth/rate-limit/network/upstream failures to existing ClipAtlas provider errors

No DashScope SDK global configuration and no TTS credentials.

### `clipatlas/asr/store.py`

`ASRStore` is a small ASR persistence boundary that uses the **same `library.sqlite3` path** as the existing library/catalog stores.

It creates only one table: `catalog_asr_chunks`.

The row is both:

- the checkpoint (`processing/completed/failed`, attempt count, bounded error)
- the transcript payload (sentences/words JSON, provider/model/revision/span)

This deliberately avoids adding ASR run/checkpoint/sentence tables and avoids a second database.

### `clipatlas/asr/indexer.py`

`ASRIndexer`:

- resumes the current revision by skipping completed chunks
- retries only failed/remaining chunks
- explicit reparse starts a new revision and preserves history
- shifts sentence/word timestamps by the chunk start offset
- rejects timestamps outside the source chunk instead of clipping them silently
- deletes successful temporary PCM chunks after persistence

There is no second automatic retry/backoff layer; recovery remains the persisted chunk checkpoint plus existing library retry/reparse behavior.

### `clipatlas/library/worker.py`

Add one optional `asr_indexer` dependency. For media with audio, the order is:

1. visual video index
2. ASR
3. existing segment/deep analysis

Media without audio skips ASR. Reparse passes `force=True` to create a new ASR revision.

### `clipatlas/app_state.py`

Build ASR only from:

- `CLIPATLAS_BAILIAN_API_KEY`
- `CLIPATLAS_BAILIAN_BASE_URL`

Use the existing Bailian endpoint helper to derive native `/api/v1`. Reuse the same library DB path, cache root and FFmpeg runner. Do not add a new top-level runtime lifecycle or new settings fields.

## TDD / verification

1. Valid RED achieved with Ruff/Mypy passing and Pytest failing because ASR implementation did not yet exist.
2. Targeted local runtime verification covers HTTP/SSE, short JSON fallback, size gate, error mapping, persistence/resume, absolute timestamp shift, revision and PCM cleanup.
3. Full isolated-branch CI remains mandatory: Ruff, Mypy, Pytest, frontend tests/typecheck/build.
4. Reverse diff must confirm no OCR, Hybrid Recall, frontend, TTS, OTIO, Jianying, retrieval or vendor changes.
5. Fast-forward the active branch only if it still points at the P0-4 base and isolated-branch CI completes with real executed steps and succeeds.

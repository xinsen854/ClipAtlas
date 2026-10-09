# ClipAtlas Video Embedding Coarse Index V0.1 Design

## Scope

This design implements only the first batch approved after the SentrySearch POC:

1. Add a dedicated video embedding provider contract and a DashScope qwen3-vl-embedding adapter.
2. Treat the effective qwen3-vl vector dimension as 2560 and validate actual returned vector length.
3. Add deterministic 30-second chunk planning with 5-second overlap for coarse video indexing.
4. Add a separate video-vector persistence namespace so 2560-dimensional video vectors never share the existing annotation/text embedding table semantics.
5. Add chunk-level checkpoint state so completed chunks can be skipped and failed chunks retried later.

Out of scope for this batch: OCR, ASR, 5-second on-demand refinement, 3-second refinement, candidate de-duplication, GPT-5.6 reranking, PySceneDetect reordering, rough-cut rewiring, OTIO/Jianying, frontend settings/progress UI.

## Constraints from the POC

- qwen3-vl-embedding returned 2560 dimensions for both video and text query embeddings even when 256/768/1024/1536 were requested.
- Native audio made no difference to the vectors in the A/B test, so this provider is visual-only in ClipAtlas.
- The proven coarse parameters are 30 s chunks with 5 s overlap.
- Preprocessed video must stay below the DashScope request-size limit; size adaptation itself is deferred to the media-preprocessing batch, but the provider must reject nonexistent local files and never pretend a request succeeded.
- Existing text embedding (`text-embedding-v4`, 1024 dimensions), annotation revision logic, Human > AI semantics, library processing, TTS, OTIO, Jianying, and current Windows URI fixes must remain unchanged.

## Architecture

### 1. Video embedding contract

Create a dedicated `VideoEmbeddingProvider` protocol instead of extending the existing text `EmbeddingProvider`. The video provider exposes:

- `name`
- `model`
- `effective_dimensions`
- `embed_video(video_path: Path) -> EmbeddingVector`
- `embed_query(text: str) -> EmbeddingVector`

Keeping the contract separate prevents the current `SemanticIndexer` from accidentally treating video vectors as annotation text vectors.

### 2. DashScope qwen3-vl adapter

Add `QwenVLVideoEmbeddingProvider` under `clipatlas/embeddings/`.

The adapter uses `dashscope.MultiModalEmbedding` because the POC proved local video upload through the official SDK works. The dependency is optional (`video-embedding` extra) so existing ClipAtlas installations do not gain a hard runtime dependency unless this feature is enabled.

The adapter:

- defaults model to `qwen3-vl-embedding`
- uses effective dimension 2560
- passes local video path for video embedding and text for query embedding
- validates HTTP/vendor success
- validates vector numeric/finite values
- validates actual vector length equals 2560
- maps authentication/rate-limit/general request errors to existing provider error types
- does not expose or log API keys

### 3. Coarse chunk planning

Add a pure helper under `clipatlas/video/chunks.py` that returns deterministic spans for a video duration.

Defaults:

- `chunk_duration_ms = 30000`
- `overlap_ms = 5000`
- step = 25000 ms

The last chunk is clipped to video duration. Invalid values (non-positive duration/chunk, negative overlap, overlap >= chunk duration) are rejected.

This batch only plans chunks; physical ffmpeg chunk materialization/preprocessing is not rewired yet.

### 4. Separate video-vector storage

Add dedicated catalog tables rather than reusing `catalog_embeddings`, because the existing table is annotation-bound (`annotation_id`, `annotation_revision`) and enforces one effective embedding per segment.

New records:

`VideoChunkEmbedding`
- id
- video_id
- start_ms
- end_ms
- provider
- model
- dimensions
- vector
- created_at

Database table: `catalog_video_chunk_embeddings`.

Uniqueness is by `(video_id, start_ms, end_ms, provider, model, dimensions)`.

This guarantees the 2560-dimensional visual index cannot deactivate or overwrite the existing 1024-dimensional annotation index.

### 5. Chunk checkpoints

Add `VideoChunkCheckpointStore`, backed by the catalog SQLite file.

Key:
`(video_id, start_ms, end_ms, provider, model)`

State:
- `pending`
- `processing`
- `completed`
- `failed`

Stored fields include `attempt_count`, `last_error`, and `updated_at`.

Rules:
- completed chunks are reusable/skippable
- failed chunks remain addressable for later retry
- checkpoint writes never modify existing prepared-media checkpoints

## Testing

TDD is required.

Tests will cover:

1. Provider contract/runtime conformance and 2560-dimension validation.
2. DashScope adapter success, dimension mismatch, missing file, auth/rate-limit mapping, and query embedding.
3. 30 s / 5 s chunk spans including short and tail chunks and invalid overlap.
4. `VideoChunkEmbedding` vector-length validation.
5. Catalog save/get/list behavior proving video vectors coexist with existing segment text embeddings without deactivation.
6. Chunk checkpoint state transitions and completed-chunk reuse semantics.

## Non-goals / anti-overreach

- No frontend changes in this batch.
- No automatic background indexing yet.
- No change to the current library worker ordering yet.
- No modification to `SemanticIndexer` behavior.
- No OCR/ASR storage.
- No ChromaDB dependency; persistence follows ClipAtlas' existing SQLite architecture for this first integrated layer.

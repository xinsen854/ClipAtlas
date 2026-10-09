# ClipAtlas Video Ingest V0.1 Design

## Goal

Build the first local-video foundation for ClipAtlas: accept a local video, persist it in development storage, probe canonical media metadata, detect shot boundaries, materialize precise `VideoSegment` records, and extract representative frames for downstream AI providers.

## Scope

This subsystem owns media preparation only. It does **not** call OpenAI, TwelveLabs, Gemini, Qwen, Doubao, or any other AI provider. It produces provider-neutral artifacts that later provider adapters consume.

### In scope

1. Local development video storage with generated ClipAtlas-owned paths.
2. `ffprobe` wrapper for duration, dimensions, average FPS, codec, and audio presence.
3. Shot-boundary detection through PySceneDetect.
4. Fallback to one full-length segment when no cut is detected.
5. Stable millisecond segment boundaries owned by ClipAtlas.
6. Representative-frame extraction through `ffmpeg` at deterministic timestamps inside each segment.
7. FastAPI upload endpoint returning the created `VideoAsset`, media metadata, segments, and frame paths.
8. Dependency injection for command runners/storage so tests never require real FFmpeg binaries or real video files.

### Out of scope

- Browser UI/video player.
- PostgreSQL/pgvector persistence.
- Cloud object storage.
- Live AI provider calls.
- Semantic annotations and human editing UI.
- Script-to-footage matching and rough-cut generation.

## Architecture

The flow is:

`multipart upload -> LocalVideoStore -> MediaProbe -> SceneDetector -> FrameExtractor -> VideoIngestService -> API response`

The service layer coordinates the flow; adapters are deliberately small and replaceable. All time values crossing into ClipAtlas domain models are integer milliseconds.

## Data contracts

### `MediaMetadata`

- `duration_ms: int > 0`
- `width: int > 0`
- `height: int > 0`
- `fps: float > 0`
- `video_codec: str`
- `has_audio: bool`

### `IngestedVideo`

- `video: VideoAsset`
- `metadata: MediaMetadata`
- `segments: list[VideoSegment]`
- `frames_by_segment: dict[UUID, list[str]]`

## Storage policy

Development storage root defaults to `./data/videos`. Each upload is written under its ClipAtlas video UUID, preserving only a sanitized extension derived from the original filename. User filenames are metadata, not storage authority.

No arbitrary client path is ever accepted for writes.

## Scene detection policy

PySceneDetect detects physical shot cuts. The adapter returns ordered `(start_ms, end_ms)` ranges.

Hard invariants:

- start >= 0
- end > start
- ranges are non-overlapping
- ranges are monotonic
- last range never exceeds probed duration
- if detector yields no ranges, emit one `[0, duration_ms]` segment

V0.1 does not merge short shots. Short-shot policy will be handled later when AI provider minimum-duration constraints are integrated.

## Representative-frame policy

For each segment, extract up to three deterministic representative frames:

- 20% of segment duration
- 50% of segment duration
- 80% of segment duration

For extremely short segments, timestamps are clamped inside the segment and duplicate millisecond timestamps are de-duplicated. Frames are JPEG files stored next to the source video under a segment-specific frame directory.

## Failure model

External tool failures are normalized into ClipAtlas ingest errors with the stage name and stderr summary. API responses never expose shell commands or secrets.

## Testing strategy

Unit tests use fake command runners and temporary directories. Tests assert exact ffprobe parsing, scene-range normalization, frame timestamp calculation, orchestration order, and endpoint behavior. CI remains Ruff + Mypy + Pytest on Python 3.12.

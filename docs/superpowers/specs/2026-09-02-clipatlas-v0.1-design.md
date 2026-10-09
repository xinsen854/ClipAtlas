# ClipAtlas V0.1 Design

## Goal

Build the first production-oriented foundation for ClipAtlas: a provider-neutral video understanding system that can ingest semantic video segments from multiple cloud or local AI backends, preserve AI output and human corrections separately, and expose stable APIs that later power searchable footage and rough-cut generation.

## Product Boundary

V0.1 is intentionally split into milestones.

### Milestone A — Core foundation

- Provider-neutral `VideoUnderstandingProvider` contract.
- Provider registry and capability discovery.
- Canonical video/segment/annotation data models.
- FastAPI service skeleton.
- Configuration through environment variables.
- Tests that do not require paid API keys.

### Milestone B — Video ingest and segmentation

- Local upload and metadata probing with FFmpeg/ffprobe.
- Scene-boundary detection with PySceneDetect.
- Stable segment timestamps owned by ClipAtlas, not by an AI vendor.

### Milestone C — Real AI providers

- TwelveLabs adapter for native video indexing/search/analysis.
- OpenAI adapter for frame-based multimodal understanding and text reasoning.
- Additional adapters (Gemini, Qwen/DashScope, Volcengine/Doubao, local models) behind the same contract.
- Provider selection based on capabilities rather than hard-coded vendor names.

### Milestone D — Human-correctable semantic timeline

- Browser video preview.
- Timeline segments with AI annotations.
- Human edits, verification, and locking.
- Revision history that never destroys the original AI result.

### Milestone E — Retrieval and rough cut

- Natural-language search over footage.
- Script decomposition and candidate retrieval.
- Candidate reranking and timeline assembly.
- OpenTimelineIO as the internal interchange boundary.
- Jianying/CapCut export implemented as an adapter, not as the core timeline model.

## Non-goals for the first implementation batch

The first coding batch does not implement Jianying export, final rough-cut logic, production cloud storage, or a full video timeline UI. Those depend on stable core contracts and will be added only after Milestone A is verified.

## Architecture Principles

1. **ClipAtlas owns canonical data.** Vendor IDs and vendor-specific payloads are metadata, never the primary data model.
2. **Provider-neutral by design.** No business logic imports a concrete provider directly.
3. **Capability-based routing.** Providers declare whether they support native video, frame/image understanding, audio, OCR, temporal search, segmentation, embeddings, or structured analysis.
4. **Precise time belongs to ClipAtlas.** AI-returned timestamps are evidence; exact shot boundaries are established by local media tooling when needed.
5. **AI and human annotations are separate.** Human correction does not overwrite the original AI output.
6. **Local-first migration path.** Cloud APIs can be used first, while the same contracts allow later replacement with self-hosted models.
7. **Test without paid services.** Core tests use fake providers and deterministic fixtures.

## Core Domain

### VideoAsset

Represents one source video owned by ClipAtlas.

Required fields:

- `id: UUID`
- `filename: str`
- `source_uri: str`
- `duration_ms: int | None`
- `width: int | None`
- `height: int | None`
- `fps: float | None`
- `created_at: datetime`

### VideoSegment

Represents a canonical time range inside a video.

Required fields:

- `id: UUID`
- `video_id: UUID`
- `start_ms: int`
- `end_ms: int`
- `source: SegmentSource`
- `created_at: datetime`

Invariant: `0 <= start_ms < end_ms`.

### SemanticAnnotation

Represents one AI or human description of a segment.

Required fields:

- `id: UUID`
- `segment_id: UUID`
- `origin: AnnotationOrigin` (`ai` or `human`)
- `provider: str | None`
- `model: str | None`
- `description: str`
- `characters: list[str]`
- `actions: list[str]`
- `scene: list[str]`
- `emotions: list[str]`
- `objects: list[str]`
- `ocr: list[str]`
- `shot_type: str | None`
- `camera_motion: str | None`
- `confidence: float | None`
- `verified: bool`
- `locked: bool`
- `revision: int`
- `raw_payload: dict[str, Any]`
- `created_at: datetime`

The effective annotation is selected by application policy: latest verified/locked human annotation first, otherwise latest human annotation, otherwise latest AI annotation. The underlying records are immutable revisions.

## Provider Contract

All video understanding backends implement `VideoUnderstandingProvider`.

### Capabilities

A provider advertises a `ProviderCapabilities` value with these booleans:

- `native_video_input`
- `image_input`
- `audio_understanding`
- `ocr`
- `temporal_search`
- `semantic_segmentation`
- `embeddings`
- `structured_output`

### Required methods

```python
class VideoUnderstandingProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def capabilities(self) -> ProviderCapabilities: ...

    async def analyze_segment(self, request: AnalyzeSegmentRequest) -> AnalyzeSegmentResult: ...
```

Optional capability-specific operations are separate protocols/interfaces rather than forced onto every provider. For example `TemporalSearchProvider` and `NativeVideoIndexProvider` can extend the base contract.

This prevents an image-only model from pretending to support native video search and prevents TwelveLabs-specific operations from contaminating the common interface.

## Provider Registry

`ProviderRegistry` stores provider instances by stable provider name and supports:

- registration with duplicate-name rejection;
- lookup by name;
- listing provider descriptors;
- filtering providers by required capabilities.

The API and future job router depend on the registry, not on concrete providers.

## API Surface — Milestone A

- `GET /health` → service health and version.
- `GET /api/v1/providers` → configured providers and capabilities.
- `POST /api/v1/providers/{provider}/analyze-segment` → provider-neutral analysis endpoint using canonical request/response schemas.

The initial repository includes a `FakeVideoUnderstandingProvider` only for deterministic tests/development. Paid providers arrive in Milestone C after the contract is stable.

## Technology

### Backend

- Python 3.12+
- FastAPI
- Pydantic v2
- Uvicorn
- pytest + pytest-asyncio
- Ruff
- mypy

### Persistence target

- PostgreSQL
- pgvector when embeddings are introduced

Persistence is not required in Milestone A; schemas are designed so SQLAlchemy storage can be added without changing provider contracts.

### Frontend target

- Next.js + TypeScript
- Browser-native video playback first
- Timeline editor implemented after core segment/annotation contracts stabilize

## Error Handling

Provider failures are normalized into ClipAtlas-level exceptions:

- `ProviderNotFoundError`
- `ProviderCapabilityError`
- `ProviderRequestError`
- `ProviderAuthenticationError`
- `ProviderRateLimitError`

HTTP routes translate these to stable API responses. Vendor raw errors may be logged internally but are not exposed as the public contract.

## Security and Secrets

- API keys only from environment variables or a future secret manager.
- `.env` is ignored; `.env.example` contains names only.
- No credentials or raw user video content are committed to Git.
- Provider adapters must not log authorization headers.

## Testing Strategy

- Domain validation tests for timestamp and confidence invariants.
- Registry tests for registration, duplicate detection, lookup, and capability filtering.
- API tests with the fake provider.
- Provider contract tests that concrete adapters must later pass.
- No real vendor request is required for unit/CI success.

## V0.1 Success Criterion

Milestone A is complete when a clean checkout can install dependencies, run the test suite, start FastAPI, list configured providers, and execute a deterministic segment-analysis request through a fake provider using the same contract future cloud/local adapters will implement.

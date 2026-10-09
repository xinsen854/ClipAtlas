import os
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path
from uuid import UUID

import httpx

from clipatlas.asr.audio import ASRAudioChunkMaterializer
from clipatlas.asr.indexer import ASRIndexer
from clipatlas.asr.qwen import QwenAudioASRProvider
from clipatlas.asr.store import ASRStore
from clipatlas.catalog.checkpoints import (
    PreparedMediaCheckpointStore,
    VideoChunkCheckpointStore,
)
from clipatlas.catalog.media_type import MediaTypeAnalyzer, annotate_video
from clipatlas.catalog.store import CatalogStore
from clipatlas.director.analyzer import DirectorAnalyzer
from clipatlas.director.service import DirectorService
from clipatlas.director.store import DirectorCacheStore
from clipatlas.embeddings.contracts import VideoEmbeddingProvider
from clipatlas.embeddings.qwen import QwenTextEmbeddingProvider
from clipatlas.embeddings.qwen_vl import QwenVLVideoEmbeddingProvider
from clipatlas.exports.contracts import JianyingBackend
from clipatlas.exports.jianying import PyJianYingDraftBackend
from clipatlas.exports.models import DEFAULT_JIANYING_DRAFT_ROOT, JianyingMode
from clipatlas.exports.otio import OtioTimelineBuilder
from clipatlas.exports.service import FineCutTimelineStoreLike, TimelineExportService
from clipatlas.library.processor import LocalFilePreparationService
from clipatlas.library.scanner import LocalFolderScanner
from clipatlas.library.store import LibraryStore
from clipatlas.library.supervisor import LibrarySupervisor
from clipatlas.library.worker import SequentialLibraryWorker
from clipatlas.ocr.frames import OCRFrameMaterializer
from clipatlas.ocr.indexer import OCRIndexer
from clipatlas.ocr.qwen import QwenOCRProvider
from clipatlas.ocr.store import OCRStore
from clipatlas.projects.store import ProjectStore
from clipatlas.providers.contracts import VideoUnderstandingProvider
from clipatlas.providers.fake import FakeVideoUnderstandingProvider
from clipatlas.providers.qwen import QwenVideoUnderstandingProvider
from clipatlas.providers.registry import ProviderRegistry
from clipatlas.providers.requests import RequestPolicy
from clipatlas.retrieval.hybrid import HybridSearchLike
from clipatlas.retrieval.indexer import SemanticIndexer
from clipatlas.retrieval.intent import QwenRetrievalIntentBuilder, RetrievalIntentBuilder
from clipatlas.retrieval.intent_search import IntentAwareHybridSearch
from clipatlas.retrieval.local_rough_cut import LocalRoughCutSearch
from clipatlas.retrieval.search import CoarseVideoSearchService, SemanticSearchService
from clipatlas.retrieval.query_cache import RequirementQueryEmbeddingService
from clipatlas.retrieval.video_indexer import CoarseVideoIndexer
from clipatlas.roughcut.contracts import SegmentSearch
from clipatlas.roughcut.planner import RoughCutPlanner
from clipatlas.roughcut.store import RoughCutStore
from clipatlas.rules.store import ProjectRuleStore
from clipatlas.settings.bailian import derive_bailian_endpoints
from clipatlas.settings.store import SettingsStore
from clipatlas.speech.audio import AudioNormalizer
from clipatlas.speech.dashscope import DashScopeSpeechProvider
from clipatlas.speech.fake import FakeSpeechProvider
from clipatlas.speech.importer import ImportedNarrationService
from clipatlas.speech.registry import SpeechProviderRegistry
from clipatlas.speech.service import NarrationService
from clipatlas.speech.store import NarrationStore
from clipatlas.system.artifacts import GeneratedArtifactRegistry
from clipatlas.system.shell import LocalShellService
from clipatlas.video.chunks import VideoChunkMaterializer
from clipatlas.video.commands import AsyncCommandRunner, SubprocessCommandRunner
from clipatlas.video.frames import FrameExtractor
from clipatlas.video.ingest import VideoIngestService
from clipatlas.video.probe import MediaProbe
from clipatlas.video.scenes import SceneDetector
from clipatlas.video.storage import LocalVideoStore

_TRUTHY = {"1", "true", "yes", "on"}
_QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_DASHSCOPE_NATIVE_BASE_URL = "https://dashscope.aliyuncs.com/api/v1"
_DASHSCOPE_SPEECH_ENDPOINT = (
    "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer"
)
_OCR_INTERVAL_SECONDS = {0, 1, 5, 10}


@dataclass(frozen=True, slots=True)
class LibraryRuntime:
    store: LibraryStore
    catalog: CatalogStore
    scanner: LocalFolderScanner
    worker: SequentialLibraryWorker
    supervisor: LibrarySupervisor
    indexer: SemanticIndexer | None
    video_indexer: CoarseVideoIndexer | None
    http_client: httpx.AsyncClient | None = None


@dataclass(frozen=True, slots=True)
class NarrationRuntime:
    root: Path
    store: NarrationStore
    audio_normalizer: AudioNormalizer
    narration_service: NarrationService | None
    imported_narration_service: ImportedNarrationService


@dataclass(frozen=True, slots=True)
class RoughCutRuntime:
    store: RoughCutStore
    planner: RoughCutPlanner | None


@dataclass(frozen=True, slots=True)
class ExportRuntime:
    service: TimelineExportService
    otio_builder: OtioTimelineBuilder
    jianying_backend: JianyingBackend | None


def build_settings_store() -> SettingsStore:
    settings_path = Path(
        os.getenv("CLIPATLAS_SETTINGS_FILE", "./data/config/settings.json")
    )
    return SettingsStore(settings_path)


def build_provider_registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    enabled = os.getenv("CLIPATLAS_ENABLE_FAKE_PROVIDER", "false").strip().lower() in _TRUTHY
    if enabled:
        registry.register(FakeVideoUnderstandingProvider())

    qwen_api_key = (
        os.getenv("CLIPATLAS_QWEN_API_KEY", "").strip()
        or os.getenv("DASHSCOPE_API_KEY", "").strip()
    )
    if qwen_api_key:
        registry.register(
            QwenVideoUnderstandingProvider(
                api_key=qwen_api_key,
                base_url=os.getenv("CLIPATLAS_QWEN_BASE_URL", _QWEN_BASE_URL).strip(),
                local_frame_root=Path(
                    os.getenv("CLIPATLAS_LIBRARY_CACHE_ROOT", "./data/library-cache")
                ),
                default_model=os.getenv(
                    "CLIPATLAS_QWEN_DEFAULT_MODEL", "qwen3.8-flash"
                ).strip(),
                long_context_model=os.getenv(
                    "CLIPATLAS_QWEN_LONG_CONTEXT_MODEL", "qwen3.8-flash"
                ).strip(),
            )
        )
    return registry


def build_speech_provider_registry() -> SpeechProviderRegistry:
    registry = SpeechProviderRegistry()
    fake_enabled = (
        os.getenv("CLIPATLAS_ENABLE_FAKE_SPEECH_PROVIDER", "false").strip().lower()
        in _TRUTHY
    )
    if fake_enabled:
        registry.register(FakeSpeechProvider())

    api_key = (
        os.getenv("CLIPATLAS_SPEECH_API_KEY", "").strip()
        or os.getenv("DASHSCOPE_API_KEY", "").strip()
    )
    if api_key:
        model = os.getenv("CLIPATLAS_SPEECH_MODEL", "cosyvoice-v3.5-flash").strip()
        if not model:
            model = "cosyvoice-v3.5-flash"
        base_url = os.getenv("CLIPATLAS_SPEECH_BASE_URL", _DASHSCOPE_SPEECH_ENDPOINT).strip()
        if not base_url or (
            "dashscope.aliyuncs.com" in base_url and "/compatible-mode/" in base_url
        ):
            base_url = _DASHSCOPE_SPEECH_ENDPOINT
        registry.register(
            DashScopeSpeechProvider(
                api_key=api_key,
                model=model,
                base_url=base_url,
            )
        )
    return registry


def _select_library_provider(registry: ProviderRegistry) -> VideoUnderstandingProvider | None:
    configured = os.getenv("CLIPATLAS_LIBRARY_PROVIDER", "").strip()
    available = {descriptor.name for descriptor in registry.list_descriptors()}
    if configured:
        if configured == "qwen":
            return registry.get("qwen") if "qwen" in available else None
        return registry.get(configured)
    if "fake" in available:
        return registry.get("fake")
    # 默认优先使用已注册的视频理解 provider（qwen），否则无法产出批注。
    for name in ("qwen", "openai-compat", "deepseek-vision", "zhipu-glm"):
        if name in available:
            return registry.get(name)
    return None


def _embedding_dimensions() -> int:
    raw = os.getenv("CLIPATLAS_EMBEDDING_DIMENSIONS", "1024").strip()
    try:
        dimensions = int(raw)
    except ValueError as exc:
        raise ValueError(
            "CLIPATLAS_EMBEDDING_DIMENSIONS must be a positive integer"
        ) from exc
    if dimensions <= 0:
        raise ValueError("CLIPATLAS_EMBEDDING_DIMENSIONS must be a positive integer")
    return dimensions


def _build_embedding_provider() -> QwenTextEmbeddingProvider | None:
    api_key = (
        os.getenv("CLIPATLAS_EMBEDDING_API_KEY", "").strip()
        or os.getenv("DASHSCOPE_API_KEY", "").strip()
    )
    if not api_key:
        return None

    base_url = (
        os.getenv("CLIPATLAS_EMBEDDING_BASE_URL", "").strip()
        or os.getenv("CLIPATLAS_QWEN_BASE_URL", "").strip()
        or _QWEN_BASE_URL
    )
    model = os.getenv("CLIPATLAS_EMBEDDING_MODEL", "text-embedding-v4").strip()
    if not model:
        model = "text-embedding-v4"

    return QwenTextEmbeddingProvider(
        api_key=api_key,
        base_url=base_url,
        model=model,
        dimensions=_embedding_dimensions(),
    )


def build_semantic_search_service(catalog: CatalogStore) -> SemanticSearchService | None:
    provider = _build_embedding_provider()
    if provider is None:
        return None
    return SemanticSearchService(store=catalog, provider=provider)


def build_requirement_query_embedding_service(
    catalog: CatalogStore,
) -> RequirementQueryEmbeddingService | None:
    if os.getenv("CLIPATLAS_REQUIREMENT_QUERY_CACHE_ENABLED", "").strip() != "1":
        return None
    provider = _build_embedding_provider()
    if provider is None:
        return None
    return RequirementQueryEmbeddingService(
        catalog=catalog,
        provider=provider,
        protocol_version="visual-retrieval-v2",
        event_index_revision=os.getenv("CLIPATLAS_EVENT_INDEX_REVISION", "timeline-v2"),
    )


def _video_embedding_base_http_api_url() -> str:
    configured = os.getenv("CLIPATLAS_EMBEDDING_BASE_URL", "").strip().rstrip("/")
    if not configured:
        return _DASHSCOPE_NATIVE_BASE_URL
    compatible_suffix = "/compatible-mode/v1"
    if configured.endswith(compatible_suffix):
        return configured[: -len(compatible_suffix)] + "/api/v1"
    return configured


def build_video_embedding_provider() -> QwenVLVideoEmbeddingProvider | None:
    api_key = (
        os.getenv("CLIPATLAS_EMBEDDING_API_KEY", "").strip()
        or os.getenv("DASHSCOPE_API_KEY", "").strip()
    )
    if not api_key:
        return None
    return QwenVLVideoEmbeddingProvider(
        api_key=api_key,
        base_http_api_url=_video_embedding_base_http_api_url(),
    )


def build_asr_indexer(
    *,
    db_path: Path,
    cache_root: Path,
    runner: AsyncCommandRunner,
    client: httpx.AsyncClient | None = None,
) -> ASRIndexer | None:
    api_key = os.getenv("CLIPATLAS_BAILIAN_API_KEY", "").strip()
    base_url = os.getenv("CLIPATLAS_BAILIAN_BASE_URL", "").strip()
    if not api_key or not base_url:
        return None
    endpoints = derive_bailian_endpoints(base_url)
    return ASRIndexer(
        store=ASRStore(db_path),
        provider=QwenAudioASRProvider(
            api_key=api_key,
            api_root=endpoints.dashscope_api_root,
            client=client,
            request_policy=RequestPolicy(rpm=int(os.getenv("CLIPATLAS_ASR_RPM", "60")), label="asr"),
        ),
        materializer=ASRAudioChunkMaterializer(
            cache_root / "asr",
            runner=runner,
        ),
        concurrency=int(os.getenv("CLIPATLAS_ASR_CONCURRENCY", "3")),
    )


def _ocr_interval_seconds() -> int:
    raw = os.getenv("CLIPATLAS_OCR_INTERVAL_SECONDS", "5").strip()
    try:
        interval = int(raw)
    except ValueError as exc:
        raise ValueError(
            "CLIPATLAS_OCR_INTERVAL_SECONDS must be 0, 1, 5, or 10"
        ) from exc
    if interval not in _OCR_INTERVAL_SECONDS:
        raise ValueError("CLIPATLAS_OCR_INTERVAL_SECONDS must be 0, 1, 5, or 10")
    return interval


def build_ocr_indexer(
    *,
    db_path: Path,
    cache_root: Path,
    runner: AsyncCommandRunner,
    client: httpx.AsyncClient | None = None,
) -> OCRIndexer | None:
    interval_seconds = _ocr_interval_seconds()
    if interval_seconds == 0:
        return None
    api_key = os.getenv("CLIPATLAS_BAILIAN_API_KEY", "").strip()
    base_url = os.getenv("CLIPATLAS_BAILIAN_BASE_URL", "").strip()
    if not api_key or not base_url:
        return None
    endpoints = derive_bailian_endpoints(base_url)
    return OCRIndexer(
        store=OCRStore(db_path),
        provider=QwenOCRProvider(
            api_key=api_key,
            base_url=endpoints.openai_compatible,
            client=client,
            request_policy=RequestPolicy(rpm=int(os.getenv("CLIPATLAS_OCR_RPM", "240")), label="ocr"),
        ),
        materializer=OCRFrameMaterializer(
            cache_root / "ocr",
            runner=runner,
        ),
        interval_ms=interval_seconds * 1000,
        concurrency=int(os.getenv("CLIPATLAS_OCR_CONCURRENCY", "12")),
    )


def build_video_chunk_search_service(
    catalog: CatalogStore,
    *,
    provider: VideoEmbeddingProvider | None = None,
) -> CoarseVideoSearchService | None:
    selected_provider = provider or build_video_embedding_provider()
    if selected_provider is None:
        return None
    return CoarseVideoSearchService(store=catalog, provider=selected_provider)


def build_retrieval_intent_builder() -> RetrievalIntentBuilder | None:
    api_key = os.getenv("CLIPATLAS_BAILIAN_API_KEY", "").strip()
    base_url = os.getenv("CLIPATLAS_BAILIAN_BASE_URL", "").strip()
    if not api_key or not base_url:
        return None
    endpoints = derive_bailian_endpoints(base_url)
    return QwenRetrievalIntentBuilder(
        api_key=api_key,
        base_url=endpoints.openai_compatible,
    )


def build_intent_aware_hybrid_search_service(
    hybrid_search_service: HybridSearchLike | None,
    *,
    builder: RetrievalIntentBuilder | None = None,
) -> HybridSearchLike | None:
    if hybrid_search_service is None or builder is None:
        return hybrid_search_service
    return IntentAwareHybridSearch(
        search=hybrid_search_service,
        builder=builder,
    )


def build_local_rough_cut_search_service(
    hybrid_search_service: HybridSearchLike | None,
    *,
    catalog: CatalogStore | None = None,
) -> LocalRoughCutSearch | None:
    if hybrid_search_service is None:
        return None
    return LocalRoughCutSearch(
        search=hybrid_search_service,
        catalog=catalog,
    )


def build_director_service(*, db_path: Path | None = None) -> DirectorService | None:
    api_key = os.getenv("CLIPATLAS_BAILIAN_API_KEY", "").strip()
    base_url = os.getenv("CLIPATLAS_BAILIAN_BASE_URL", "").strip()
    if not api_key or not base_url:
        return None
    endpoints = derive_bailian_endpoints(base_url)
    store = DirectorCacheStore(
        db_path or Path(os.getenv("CLIPATLAS_DIRECTOR_DB", "./data/director/director.sqlite3"))
    )
    return DirectorService(
        analyzer=DirectorAnalyzer(api_key=api_key, base_url=endpoints.openai_compatible),
        store=store,
    )


def build_semantic_indexer(catalog: CatalogStore) -> SemanticIndexer | None:
    provider = _build_embedding_provider()
    if provider is None:
        return None
    return SemanticIndexer(store=catalog, provider=provider)


def build_project_store() -> ProjectStore:
    db_path = Path(os.getenv("CLIPATLAS_PROJECT_DB", "./data/projects/projects.sqlite3"))
    return ProjectStore(db_path)


def build_video_ingest_service() -> VideoIngestService:
    root = Path(os.getenv("CLIPATLAS_VIDEO_ROOT", "./data/videos"))
    return VideoIngestService(
        store=LocalVideoStore(root),
        probe=MediaProbe(),
        scene_detector=SceneDetector(),
        frame_extractor=FrameExtractor(),
    )


class _CatalogMediaTypeAnnotator:
    def __init__(self, store: CatalogStore, analyzer: MediaTypeAnalyzer) -> None:
        self._store = store
        self._analyzer = analyzer

    async def annotate_video(
        self, video_id: UUID, *, force: bool = False,
    ) -> dict[str, int]:
        return await annotate_video(
            self._store, self._analyzer, video_id, force=force,
            concurrency=int(os.getenv("CLIPATLAS_MEDIATYPE_CONCURRENCY", "6")),
        )


def _build_media_type_annotator(
    catalog: CatalogStore,
) -> _CatalogMediaTypeAnnotator | None:
    api_key = (
        os.getenv("CLIPATLAS_QWEN_API_KEY", "").strip()
        or os.getenv("DASHSCOPE_API_KEY", "").strip()
    )
    base_url = os.getenv("CLIPATLAS_QWEN_BASE_URL", _QWEN_BASE_URL).strip()
    if not api_key or not base_url:
        return None
    model = os.getenv("CLIPATLAS_QWEN_DEFAULT_MODEL", "qwen3.8-flash").strip()
    try:
        analyzer = MediaTypeAnalyzer(
            api_key=api_key,
            base_url=base_url,
            model=model,
        )
    except ValueError:
        return None
    return _CatalogMediaTypeAnnotator(store=catalog, analyzer=analyzer)


def build_library_runtime(
    registry: ProviderRegistry | None = None,
    *,
    video_embedding_provider: VideoEmbeddingProvider | None = None,
) -> LibraryRuntime:
    db_path = Path(os.getenv("CLIPATLAS_LIBRARY_DB", "./data/library/library.sqlite3"))
    cache_root = Path(os.getenv("CLIPATLAS_LIBRARY_CACHE_ROOT", "./data/library-cache"))
    interval_seconds = float(os.getenv("CLIPATLAS_LIBRARY_SCAN_INTERVAL_SECONDS", "60"))

    providers = registry or build_provider_registry()
    provider = _select_library_provider(providers)
    store = LibraryStore(db_path)
    catalog = CatalogStore(db_path)
    checkpoints = PreparedMediaCheckpointStore(db_path)
    scanner = LocalFolderScanner(store)
    runner = SubprocessCommandRunner(
        concurrency=int(os.getenv("CLIPATLAS_LIBRARY_FFMPEG_CONCURRENCY", "1")),
    )
    http_client = httpx.AsyncClient(limits=httpx.Limits(
        max_connections=32, max_keepalive_connections=16,
    ))
    processor = LocalFilePreparationService(
        probe=MediaProbe(runner=runner),
        scene_detector=SceneDetector(),
        cache_root=cache_root,
        runner=runner,
    )
    indexer = build_semantic_indexer(catalog)
    video_indexer = None
    if video_embedding_provider is not None:
        video_indexer = CoarseVideoIndexer(
            catalog_store=catalog,
            checkpoint_store=VideoChunkCheckpointStore(db_path),
            provider=video_embedding_provider,
            materializer=VideoChunkMaterializer(runner=runner),
            chunk_root=cache_root / "video-chunks",
            concurrency=int(os.getenv("CLIPATLAS_VISUAL_CONCURRENCY", "4")),
        )
    asr_indexer = build_asr_indexer(
        db_path=db_path,
        cache_root=cache_root,
        runner=runner,
        client=http_client,
    )
    ocr_indexer = build_ocr_indexer(
        db_path=db_path,
        cache_root=cache_root,
        runner=runner,
        client=http_client,
    )
    media_type_annotator = _build_media_type_annotator(catalog)
    worker = SequentialLibraryWorker(
        store=store,
        processor=processor,
        catalog=catalog,
        provider=provider,
        checkpoints=checkpoints,
        indexer=indexer,
        video_indexer=video_indexer,
        asr_indexer=asr_indexer,
        ocr_indexer=ocr_indexer,
        media_type_annotator=media_type_annotator,
    )
    supervisor = LibrarySupervisor(
        store=store,
        scanner=scanner,
        worker=worker,
        interval_seconds=interval_seconds,
        processing_enabled=any((provider, video_indexer, asr_indexer, ocr_indexer)),
    )
    return LibraryRuntime(
        store=store,
        catalog=catalog,
        scanner=scanner,
        worker=worker,
        supervisor=supervisor,
        indexer=indexer,
        video_indexer=video_indexer,
        http_client=http_client,
    )


def build_narration_runtime(
    registry: SpeechProviderRegistry | None = None,
    *,
    rule_store: ProjectRuleStore | None = None,
) -> NarrationRuntime:
    narration_root = Path(os.getenv("CLIPATLAS_NARRATION_ROOT", "./data/narration")).resolve()
    narration_root.mkdir(parents=True, exist_ok=True)
    store = NarrationStore(narration_root / "narration.sqlite3")
    audio_normalizer = AudioNormalizer()
    imported = ImportedNarrationService(
        store=store,
        audio_normalizer=audio_normalizer,
        narration_root=narration_root,
        rule_store=rule_store,
    )
    providers = registry or build_speech_provider_registry()
    narration_service = None
    if providers.list_descriptors():
        narration_service = NarrationService(
            registry=providers,
            store=store,
            audio_normalizer=audio_normalizer,
            narration_root=narration_root,
            rule_store=rule_store,
        )
    return NarrationRuntime(
        root=narration_root,
        store=store,
        audio_normalizer=audio_normalizer,
        narration_service=narration_service,
        imported_narration_service=imported,
    )


def build_rough_cut_runtime(
    narration_store: NarrationStore,
    search_service: SegmentSearch | None,
    *,
    rule_store: ProjectRuleStore | None = None,
    audio_normalizer: AudioNormalizer | None = None,
    story_audio_root: Path | None = None,
) -> RoughCutRuntime:
    store = RoughCutStore(
        Path(os.getenv("CLIPATLAS_ROUGHCUT_DB", "./data/roughcut/roughcut.sqlite3"))
    )
    search = search_service
    planner = None
    if search is not None:
        from clipatlas.speech.narration_alignment import NarrationAlignmentService
        from clipatlas.asr.qwen import QwenAudioASRProvider
        key = os.getenv("CLIPATLAS_BAILIAN_API_KEY", "").strip()
        base = os.getenv("CLIPATLAS_BAILIAN_BASE_URL", "").strip()
        alignment_service = None
        if key and base:
            alignment_service = NarrationAlignmentService(
                store=narration_store,
                provider=QwenAudioASRProvider(
                    api_key=key, api_root=derive_bailian_endpoints(base).dashscope_api_root,
                ),
                root=Path(os.getenv("CLIPATLAS_NARRATION_ROOT", "./data/narration")),
            )
        planner = RoughCutPlanner(
            narration_store=narration_store,
            search=search,
            store=store,
            rule_store=rule_store,
            alignment_service=alignment_service,
            director=build_director_service(),
            audio_normalizer=audio_normalizer,
            story_audio_root=story_audio_root,
        )
    return RoughCutRuntime(store=store, planner=planner)


def build_local_shell_service(registry: GeneratedArtifactRegistry) -> LocalShellService:
    draft_root_raw = (
        os.getenv("CLIPATLAS_JIANYING_DRAFT_ROOT", "").strip()
        or DEFAULT_JIANYING_DRAFT_ROOT
    )
    install_dir_raw = os.getenv("CLIPATLAS_JIANYING_INSTALL_DIR", "").strip()
    executable_raw = os.getenv("CLIPATLAS_JIANYING_EXECUTABLE", "").strip()
    return LocalShellService(
        registry=registry,
        draft_root=Path(draft_root_raw) if draft_root_raw else None,
        jianying_install_dir=Path(install_dir_raw) if install_dir_raw else None,
        jianying_executable=Path(executable_raw) if executable_raw else None,
    )


def build_export_runtime(
    rough_cut_store: RoughCutStore,
    narration_store: NarrationStore,
    *,
    finecut_timeline_store: FineCutTimelineStoreLike | None = None,
) -> ExportRuntime:
    export_root = Path(os.getenv("CLIPATLAS_EXPORT_ROOT", "./data/exports")).resolve()
    draft_root = (
        os.getenv("CLIPATLAS_JIANYING_DRAFT_ROOT", "").strip()
        or DEFAULT_JIANYING_DRAFT_ROOT
    )
    mode_raw = os.getenv("CLIPATLAS_JIANYING_MODE", "portable").strip()
    install_dir = os.getenv("CLIPATLAS_JIANYING_INSTALL_DIR", "").strip()
    user_data_dir = os.getenv("CLIPATLAS_JIANYING_USER_DATA", "").strip()

    jianying_backend: JianyingBackend | None = None
    if draft_root and find_spec("pyJianYingDraft") is not None:
        try:
            mode = JianyingMode(mode_raw)
        except ValueError:
            mode = None
        if mode == JianyingMode.PORTABLE:
            jianying_backend = PyJianYingDraftBackend()
        elif mode == JianyingMode.JIANYING_PRO_10_8 and install_dir and user_data_dir:
            jianying_backend = None

    otio_builder = OtioTimelineBuilder()
    service = TimelineExportService(
        rough_cut_store=rough_cut_store,
        narration_store=narration_store,
        export_root=export_root,
        otio_builder=otio_builder,
        jianying_backend=jianying_backend,
        finecut_timeline_store=finecut_timeline_store,
    )
    return ExportRuntime(
        service=service,
        otio_builder=otio_builder,
        jianying_backend=jianying_backend,
    )

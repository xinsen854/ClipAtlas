import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from clipatlas import __version__
from clipatlas.api.errors import register_error_handlers
from clipatlas.api.maintenance import install_maintenance_gate
from clipatlas.api.routes.auto_director import router as auto_director_router
from clipatlas.api.routes.exports import router as exports_router
from clipatlas.api.routes.hypit import router as hypit_router
from clipatlas.api.routes.index_results import router as index_results_router
from clipatlas.api.routes.library import router as library_router
from clipatlas.api.routes.narration_batches import router as narration_batches_router
from clipatlas.api.routes.projects import router as projects_router
from clipatlas.api.routes.providers import router as providers_router
from clipatlas.api.routes.rough_cut import router as rough_cut_router
from clipatlas.api.routes.rules import router as rules_router
from clipatlas.api.routes.search import router as search_router
from clipatlas.api.routes.segment_roles import router as segment_roles_router
from clipatlas.api.routes.settings import router as settings_router
from clipatlas.api.routes.speech import router as speech_router
from clipatlas.api.routes.system import router as system_router
from clipatlas.api.routes.videos import router as videos_router
from clipatlas.app_state import (
    build_export_runtime,
    build_intent_aware_hybrid_search_service,
    build_library_runtime,
    build_local_rough_cut_search_service,
    build_local_shell_service,
    build_narration_runtime,
    build_project_store,
    build_provider_registry,
    build_requirement_query_embedding_service,
    build_retrieval_intent_builder,
    build_rough_cut_runtime,
    build_semantic_search_service,
    build_settings_store,
    build_speech_provider_registry,
    build_video_chunk_search_service,
    build_video_embedding_provider,
    build_video_ingest_service,
)
from clipatlas.asr.store import ASRStore
from clipatlas.director.reranker import CandidateReranker
from clipatlas.director.story_analyzer import StoryAnalyzer
from clipatlas.director.story_evidence import StoryEvidenceBuilder
from clipatlas.director.story_service import StoryDirectorService
from clipatlas.director.story_store import StoryOutlineStore
from clipatlas.hypit import HypitService
from clipatlas.hypit.service import HypitConfigurationError
from clipatlas.library.index_progress import LibraryIndexProgressReader
from clipatlas.library.maintenance import LibraryMaintenance
from clipatlas.ocr.store import OCRStore
from clipatlas.projects.maintenance import ProjectMaintenance
from clipatlas.providers.registry import ProviderRegistry
from clipatlas.retrieval.fallback_roles import SegmentFallbackSearch
from clipatlas.retrieval.hybrid import build_hybrid_search_service
from clipatlas.retrieval.reranked_rough_cut import RerankedRoughCutSearch
from clipatlas.rules.analyzer import QwenRuleAnalyzer
from clipatlas.rules.store import ProjectRuleStore
from clipatlas.settings.bailian import derive_bailian_endpoints
from clipatlas.settings.probe import ServiceProbe
from clipatlas.speech.original_audio import OriginalAudioNarrationAdapter
from clipatlas.speech.story_tts import StoryTtsNarrationAdapter
from clipatlas.system.artifacts import GeneratedArtifactRegistry
from clipatlas.web import mount_finecut_routes, mount_frontend


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    stop = asyncio.Event()
    supervisor_task = asyncio.create_task(app.state.library_supervisor.run_forever(stop))
    await asyncio.sleep(0)
    if supervisor_task.done():
        supervisor_task.result()
    app.state.hypit_auto_start_error = None
    if os.environ.get("CLIPATLAS_HYPIT_AUTO_START", "").strip() == "1":
        try:
            app.state.hypit_service.start()
        except (HypitConfigurationError, OSError, RuntimeError) as exc:
            app.state.hypit_auto_start_error = str(exc)
            print(f"Hypit 自动启动失败：{exc}", flush=True)
    try:
        yield
    finally:
        app.state.hypit_service.stop()
        app.state.library_supervisor.pause()
        stop.set()
        try:
            await supervisor_task
        finally:
            await app.state.library_http_client.aclose()


def create_app(registry: ProviderRegistry | None = None) -> FastAPI:
    app = FastAPI(title="ClipAtlas API", version=__version__, lifespan=_lifespan)
    install_maintenance_gate(app)

    app.state.settings_store = build_settings_store()
    app.state.settings_store.apply_missing_environment()
    app.state.service_probe = ServiceProbe()
    app.state.hypit_service = HypitService.from_environment()

    app.state.project_store = build_project_store()
    app.state.project_rule_store = ProjectRuleStore(
        Path(
            os.getenv(
                "CLIPATLAS_PROJECT_RULE_DB",
                "./data/projects/project_rules.sqlite3",
            )
        )
    )
    bailian_api_key = os.getenv("CLIPATLAS_BAILIAN_API_KEY", "").strip()
    bailian_base_url = os.getenv("CLIPATLAS_BAILIAN_BASE_URL", "").strip()
    app.state.project_rule_analyzer = None
    if bailian_api_key and bailian_base_url:
        app.state.project_rule_analyzer = QwenRuleAnalyzer(
            api_key=bailian_api_key,
            base_url=derive_bailian_endpoints(bailian_base_url).openai_compatible,
        )

    app.state.provider_registry = registry or build_provider_registry()
    app.state.video_ingest_service = build_video_ingest_service()
    app.state.video_embedding_provider = build_video_embedding_provider()
    library_runtime = build_library_runtime(
        app.state.provider_registry,
        video_embedding_provider=app.state.video_embedding_provider,
    )
    app.state.library_store = library_runtime.store
    app.state.library_catalog = library_runtime.catalog
    app.state.library_scanner = library_runtime.scanner
    app.state.library_worker = library_runtime.worker
    app.state.library_supervisor = library_runtime.supervisor
    app.state.library_http_client = library_runtime.http_client
    app.state.library_legacy_roots_migrated = (
        library_runtime.store.migrate_legacy_project_ownership(
            app.state.project_store.list_projects()
        )
    )
    app.state.semantic_indexer = library_runtime.indexer
    app.state.semantic_search_service = build_semantic_search_service(library_runtime.catalog)
    app.state.requirement_query_embedding_service = (
        build_requirement_query_embedding_service(library_runtime.catalog)
    )
    app.state.video_chunk_search_service = build_video_chunk_search_service(
        library_runtime.catalog,
        provider=app.state.video_embedding_provider,
    )
    library_db_path = Path(
        os.getenv("CLIPATLAS_LIBRARY_DB", "./data/library/library.sqlite3")
    )
    bailian_enabled = bool(bailian_api_key and bailian_base_url)
    app.state.library_asr_store = ASRStore(library_db_path)
    app.state.library_maintenance = LibraryMaintenance(
        library_db_path,
        Path(os.getenv("CLIPATLAS_LIBRARY_CACHE_ROOT", "./data/library-cache")),
    )
    app.state.library_ocr_store = OCRStore(library_db_path)
    ocr_interval_seconds = int(os.getenv("CLIPATLAS_OCR_INTERVAL_SECONDS", "5").strip())
    app.state.library_index_progress = LibraryIndexProgressReader(
        library_db_path,
        visual_enabled=app.state.video_embedding_provider is not None,
        asr_enabled=bailian_enabled,
        ocr_interval_ms=(
            ocr_interval_seconds * 1000
            if bailian_enabled and ocr_interval_seconds > 0
            else None
        ),
    )

    story_analyzer = None
    if bailian_enabled:
        story_analyzer = StoryAnalyzer(
            api_key=bailian_api_key,
            base_url=derive_bailian_endpoints(bailian_base_url).openai_compatible,
        )
    app.state.story_director_service = StoryDirectorService(
        evidence_builder=StoryEvidenceBuilder(
            library_store=library_runtime.store,
            catalog_store=library_runtime.catalog,
            asr_store=app.state.library_asr_store,
            ocr_store=app.state.library_ocr_store,
        ),
        analyzer=story_analyzer,
        store=StoryOutlineStore(
            Path(
                os.getenv(
                    "CLIPATLAS_DIRECTOR_DB",
                    "./data/director/director.sqlite3",
                )
            )
        ),
    )

    app.state.hybrid_search_service = build_hybrid_search_service(
        catalog=library_runtime.catalog,
        visual_service=app.state.video_chunk_search_service,
        db_path=library_db_path,
    )
    app.state.retrieval_intent_builder = build_retrieval_intent_builder()
    app.state.intent_aware_hybrid_search_service = build_intent_aware_hybrid_search_service(
        app.state.hybrid_search_service,
        builder=app.state.retrieval_intent_builder,
    )
    app.state.rough_cut_search_service = build_local_rough_cut_search_service(
        app.state.intent_aware_hybrid_search_service, catalog=library_runtime.catalog,
    )
    if app.state.rough_cut_search_service is not None:
        app.state.rough_cut_search_service = SegmentFallbackSearch(
            app.state.rough_cut_search_service,
            catalog=library_runtime.catalog,
        )

    # Optional second-stage API: local evidence/media admission remains the
    # judge; this API only ranks already-legal candidates by editorial fit.
    # It is enabled by default whenever Bailian is configured because the
    # rough-cut workflow explicitly wants a less mechanical choice among
    # several equally valid local shots. Set CLIPATLAS_CANDIDATE_RERANK_ENABLED=0
    # for a strictly local editing stage.
    app.state.candidate_reranker = None
    rerank_enabled = os.getenv(
        "CLIPATLAS_CANDIDATE_RERANK_ENABLED", "1"
    ).strip().lower() not in {"0", "false", "no", "off"}
    if (
        rerank_enabled
        and app.state.rough_cut_search_service is not None
        and bailian_api_key
        and bailian_base_url
    ):
        endpoints = derive_bailian_endpoints(bailian_base_url)
        app.state.candidate_reranker = CandidateReranker(
            api_key=bailian_api_key,
            base_url=endpoints.openai_compatible,
            model=os.getenv("CLIPATLAS_CANDIDATE_RERANK_MODEL", "qwen3.8-flash").strip()
            or "qwen3.8-flash",
        )
        app.state.rough_cut_search_service = RerankedRoughCutSearch(
            app.state.rough_cut_search_service,
            reranker=app.state.candidate_reranker,
        )

    app.state.speech_registry = build_speech_provider_registry()
    narration_runtime = build_narration_runtime(
        app.state.speech_registry,
        rule_store=app.state.project_rule_store,
    )
    app.state.narration_root = narration_runtime.root
    app.state.narration_store = narration_runtime.store
    app.state.audio_normalizer = narration_runtime.audio_normalizer
    app.state.narration_service = narration_runtime.narration_service
    app.state.imported_narration_service = narration_runtime.imported_narration_service
    app.state.narration_batch_lock = asyncio.Lock()
    app.state.original_audio_narration = OriginalAudioNarrationAdapter(
        narration_store=narration_runtime.store,
        catalog=library_runtime.catalog,
        asr_store=app.state.library_asr_store,
        audio_normalizer=narration_runtime.audio_normalizer,
        narration_root=narration_runtime.root,
    )
    app.state.story_tts_narration = (
        StoryTtsNarrationAdapter(
            service=narration_runtime.narration_service,
            store=narration_runtime.store,
        )
        if narration_runtime.narration_service is not None
        else None
    )

    rough_cut_runtime = build_rough_cut_runtime(
        narration_runtime.store,
        app.state.rough_cut_search_service,
        rule_store=app.state.project_rule_store,
        audio_normalizer=narration_runtime.audio_normalizer,
        story_audio_root=narration_runtime.root,
    )
    app.state.rough_cut_store = rough_cut_runtime.store
    app.state.rough_cut_planner = rough_cut_runtime.planner

    finecut_timeline_store = mount_finecut_routes(app)
    export_runtime = build_export_runtime(
        rough_cut_runtime.store,
        narration_runtime.store,
        finecut_timeline_store=finecut_timeline_store,
    )
    app.state.export_service = export_runtime.service
    app.state.otio_builder = export_runtime.otio_builder
    app.state.jianying_backend = export_runtime.jianying_backend
    app.state.project_maintenance = ProjectMaintenance(
        project_db=app.state.project_store._db_path,
        narration_db=narration_runtime.store._db_path,
        roughcut_db=rough_cut_runtime.store._db_path,
        rules_db=app.state.project_rule_store._db_path,
        narration_root=narration_runtime.root,
        export_root=Path(os.getenv('CLIPATLAS_EXPORT_ROOT', './data/exports')),
        library_db=library_db_path,
    )

    generated_artifact_registry = GeneratedArtifactRegistry()
    app.state.generated_artifact_registry = generated_artifact_registry
    app.state.local_shell_service = build_local_shell_service(generated_artifact_registry)

    register_error_handlers(app)
    app.include_router(projects_router)
    app.include_router(rules_router)
    app.include_router(providers_router)
    app.include_router(videos_router)
    app.include_router(index_results_router)
    app.include_router(library_router)
    app.include_router(segment_roles_router)
    app.include_router(search_router)
    app.include_router(settings_router)
    app.include_router(hypit_router)
    app.include_router(speech_router)
    app.include_router(narration_batches_router)
    app.include_router(auto_director_router)
    app.include_router(rough_cut_router)
    app.include_router(exports_router)
    app.include_router(system_router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "clipatlas", "version": __version__}

    frontend_dist = Path(os.environ.get("CLIPATLAS_FRONTEND_DIST", "frontend/dist"))
    mount_frontend(app, frontend_dist)

    return app


app = create_app()

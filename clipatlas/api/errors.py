from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from clipatlas.director.story_errors import (
    AutoDirectorUnavailableError,
    StoryEvidenceUnavailableError,
    StoryOutlineConflictError,
    StoryOutlineNotFoundError,
    StorySkillError,
)
from clipatlas.exports.errors import (
    ExportInvariantError,
    ExportNotReadyError,
    ExportPlanNotFoundError,
    JianyingConfigurationError,
    JianyingDependencyError,
    JianyingMediaError,
    JianyingUnavailableError,
    JianyingWriteError,
    OtioSerializationError,
)
from clipatlas.providers.errors import (
    ProviderAuthenticationError,
    ProviderNotFoundError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderStructuredOutputError,
)
from clipatlas.roughcut.errors import (
    RoughCutConfigurationError,
    RoughCutPlanningError,
    RoughCutPlanNotFoundError,
    RoughCutRetrievalError,
    RoughCutTimingError,
    RoughCutUnavailableError,
)
from clipatlas.speech.errors import (
    SpeechAudioValidationError,
    SpeechAuthenticationError,
    SpeechConfigurationError,
    SpeechProfileNotFoundError,
    SpeechProviderUnavailableError,
    SpeechRateLimitError,
    SpeechRequestError,
)
from clipatlas.system.shell import (
    GeneratedArtifactNotFoundError,
    GeneratedArtifactPathError,
    LocalSystemActionFailedError,
    LocalSystemConfigurationError,
    LocalSystemUnsupportedError,
)


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(GeneratedArtifactNotFoundError)
    async def handle_generated_artifact_not_found(
        request: Request, exc: GeneratedArtifactNotFoundError
    ) -> JSONResponse:
        del request
        return _error_response(404, "generated_artifact_not_found", str(exc))

    @app.exception_handler(GeneratedArtifactPathError)
    async def handle_generated_artifact_path(
        request: Request, exc: GeneratedArtifactPathError
    ) -> JSONResponse:
        del request
        return _error_response(409, "generated_artifact_invalid", str(exc))

    @app.exception_handler(LocalSystemConfigurationError)
    async def handle_local_system_configuration(
        request: Request, exc: LocalSystemConfigurationError
    ) -> JSONResponse:
        del request
        return _error_response(409, "local_system_not_configured", str(exc))

    @app.exception_handler(LocalSystemUnsupportedError)
    async def handle_local_system_unsupported(
        request: Request, exc: LocalSystemUnsupportedError
    ) -> JSONResponse:
        del request
        return _error_response(409, "local_system_unsupported", str(exc))

    @app.exception_handler(LocalSystemActionFailedError)
    async def handle_local_system_action_failed(
        request: Request, exc: LocalSystemActionFailedError
    ) -> JSONResponse:
        del request
        return _error_response(500, "local_system_action_failed", str(exc))

    @app.exception_handler(ProviderNotFoundError)
    async def handle_provider_not_found(
        request: Request, exc: ProviderNotFoundError
    ) -> JSONResponse:
        del request
        return _error_response(404, "provider_not_found", str(exc))

    @app.exception_handler(ProviderAuthenticationError)
    async def handle_provider_auth(
        request: Request, exc: ProviderAuthenticationError
    ) -> JSONResponse:
        del request
        return _error_response(502, "provider_authentication_failed", str(exc))

    @app.exception_handler(ProviderRateLimitError)
    async def handle_provider_rate_limit(
        request: Request, exc: ProviderRateLimitError
    ) -> JSONResponse:
        del request
        return _error_response(503, "provider_rate_limited", str(exc))

    @app.exception_handler(ProviderStructuredOutputError)
    async def handle_provider_structure(
        request: Request, exc: ProviderStructuredOutputError,
    ) -> JSONResponse:
        del request
        return _error_response(502, 'provider_invalid_structured_output', str(exc))

    @app.exception_handler(ProviderRequestError)
    async def handle_provider_request(
        request: Request, exc: ProviderRequestError
    ) -> JSONResponse:
        del request
        return _error_response(502, "provider_request_failed", str(exc))

    @app.exception_handler(AutoDirectorUnavailableError)
    async def handle_auto_director_unavailable(
        request: Request, exc: AutoDirectorUnavailableError
    ) -> JSONResponse:
        del request
        return _error_response(503, "auto_director_unavailable", str(exc))

    @app.exception_handler(StorySkillError)
    async def handle_story_skill_error(
        request: Request, exc: StorySkillError
    ) -> JSONResponse:
        del request
        return _error_response(422, "story_skill_invalid", str(exc))

    @app.exception_handler(StoryEvidenceUnavailableError)
    async def handle_story_evidence_unavailable(
        request: Request, exc: StoryEvidenceUnavailableError
    ) -> JSONResponse:
        del request
        return _error_response(409, "story_evidence_unavailable", str(exc))

    @app.exception_handler(StoryOutlineNotFoundError)
    async def handle_story_outline_not_found(
        request: Request, exc: StoryOutlineNotFoundError
    ) -> JSONResponse:
        del request
        return _error_response(404, "story_outline_not_found", str(exc))

    @app.exception_handler(StoryOutlineConflictError)
    async def handle_story_outline_conflict(
        request: Request, exc: StoryOutlineConflictError
    ) -> JSONResponse:
        del request
        return _error_response(409, "story_outline_conflict", str(exc))

    @app.exception_handler(SpeechAuthenticationError)
    async def handle_speech_auth(
        request: Request, exc: SpeechAuthenticationError
    ) -> JSONResponse:
        del request
        return _error_response(502, "speech_auth_failed", str(exc))

    @app.exception_handler(SpeechRateLimitError)
    async def handle_speech_rate_limit(
        request: Request, exc: SpeechRateLimitError
    ) -> JSONResponse:
        del request
        return _error_response(503, "speech_rate_limited", str(exc))

    @app.exception_handler(SpeechRequestError)
    async def handle_speech_request(
        request: Request, exc: SpeechRequestError
    ) -> JSONResponse:
        del request
        return _error_response(502, "speech_request_failed", str(exc))

    @app.exception_handler(SpeechAudioValidationError)
    async def handle_speech_audio(
        request: Request, exc: SpeechAudioValidationError
    ) -> JSONResponse:
        del request
        return _error_response(500, "speech_audio_invalid", str(exc))

    @app.exception_handler(SpeechConfigurationError)
    async def handle_speech_configuration(
        request: Request, exc: SpeechConfigurationError
    ) -> JSONResponse:
        del request
        return _error_response(422, "speech_configuration_invalid", str(exc))

    @app.exception_handler(SpeechProfileNotFoundError)
    async def handle_speech_profile_not_found(
        request: Request, exc: SpeechProfileNotFoundError
    ) -> JSONResponse:
        del request
        return _error_response(404, "speech_profile_not_found", str(exc))

    @app.exception_handler(SpeechProviderUnavailableError)
    async def handle_speech_provider_unavailable(
        request: Request, exc: SpeechProviderUnavailableError
    ) -> JSONResponse:
        del request
        return _error_response(503, "speech_provider_unavailable", str(exc))

    @app.exception_handler(RoughCutUnavailableError)
    async def handle_rough_cut_unavailable(
        request: Request, exc: RoughCutUnavailableError
    ) -> JSONResponse:
        del request
        return _error_response(503, "rough_cut_unavailable", str(exc))

    @app.exception_handler(RoughCutPlanNotFoundError)
    async def handle_rough_cut_plan_not_found(
        request: Request, exc: RoughCutPlanNotFoundError
    ) -> JSONResponse:
        del request
        return _error_response(404, "rough_cut_plan_not_found", str(exc))

    @app.exception_handler(RoughCutConfigurationError)
    async def handle_rough_cut_configuration(
        request: Request, exc: RoughCutConfigurationError
    ) -> JSONResponse:
        del request
        return _error_response(409, "rough_cut_not_ready", str(exc))

    @app.exception_handler(RoughCutTimingError)
    async def handle_rough_cut_timing(
        request: Request, exc: RoughCutTimingError
    ) -> JSONResponse:
        del request
        return _error_response(409, "rough_cut_not_ready", str(exc))

    @app.exception_handler(RoughCutRetrievalError)
    async def handle_rough_cut_retrieval(
        request: Request, exc: RoughCutRetrievalError
    ) -> JSONResponse:
        del request
        return _error_response(503, "rough_cut_retrieval_failed", str(exc))

    @app.exception_handler(RoughCutPlanningError)
    async def handle_rough_cut_planning(
        request: Request, exc: RoughCutPlanningError
    ) -> JSONResponse:
        del request
        return _error_response(500, "rough_cut_planning_failed", str(exc))

    @app.exception_handler(ExportPlanNotFoundError)
    async def handle_export_plan_not_found(
        request: Request, exc: ExportPlanNotFoundError
    ) -> JSONResponse:
        del request
        return _error_response(404, "export_plan_not_found", str(exc))

    @app.exception_handler(ExportNotReadyError)
    async def handle_export_not_ready(
        request: Request, exc: ExportNotReadyError
    ) -> JSONResponse:
        del request
        return _error_response(409, "export_not_ready", str(exc))

    @app.exception_handler(ExportInvariantError)
    async def handle_export_invariant(
        request: Request, exc: ExportInvariantError
    ) -> JSONResponse:
        del request
        return _error_response(500, "export_invariant_failed", str(exc))

    @app.exception_handler(OtioSerializationError)
    async def handle_otio_serialization(
        request: Request, exc: OtioSerializationError
    ) -> JSONResponse:
        del request
        return _error_response(500, "otio_serialization_failed", str(exc))

    @app.exception_handler(JianyingUnavailableError)
    async def handle_jianying_unavailable(
        request: Request, exc: JianyingUnavailableError
    ) -> JSONResponse:
        del request
        return _error_response(503, "jianying_unavailable", str(exc))

    @app.exception_handler(JianyingDependencyError)
    async def handle_jianying_dependency(
        request: Request, exc: JianyingDependencyError
    ) -> JSONResponse:
        del request
        return _error_response(503, "jianying_dependency_missing", str(exc))

    @app.exception_handler(JianyingConfigurationError)
    async def handle_jianying_configuration(
        request: Request, exc: JianyingConfigurationError
    ) -> JSONResponse:
        del request
        return _error_response(409, "jianying_not_configured", str(exc))

    @app.exception_handler(JianyingMediaError)
    async def handle_jianying_media(
        request: Request, exc: JianyingMediaError
    ) -> JSONResponse:
        del request
        return _error_response(422, "jianying_media_unsupported", str(exc))

    @app.exception_handler(JianyingWriteError)
    async def handle_jianying_write(
        request: Request, exc: JianyingWriteError
    ) -> JSONResponse:
        del request
        return _error_response(500, "jianying_write_failed", str(exc))

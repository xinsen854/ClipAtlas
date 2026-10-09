from importlib import import_module
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from clipatlas.api.errors import register_error_handlers
from clipatlas.exports.errors import (
    ExportInvariantError,
    ExportNotReadyError,
    ExportPlanNotFoundError,
    JianyingDependencyError,
    JianyingMediaError,
    JianyingUnavailableError,
    JianyingWriteError,
    OtioSerializationError,
)
from clipatlas.exports.models import (
    DEFAULT_JIANYING_DRAFT_ROOT,
    JianyingDraftArtifact,
    JianyingExportSettings,
    JianyingMode,
    OtioExportArtifact,
)
from clipatlas.system.artifacts import GeneratedArtifactRegistry


class StubExportService:
    def __init__(
        self,
        *,
        otio_error: Exception | None = None,
        jianying_error: Exception | None = None,
    ) -> None:
        self.otio_error = otio_error
        self.jianying_error = jianying_error
        self.otio_calls: list[UUID] = []
        self.jianying_calls: list[tuple[UUID, str, JianyingExportSettings]] = []

    def export_otio(self, plan_id: UUID) -> OtioExportArtifact:
        self.otio_calls.append(plan_id)
        if self.otio_error is not None:
            raise self.otio_error
        return OtioExportArtifact(
            plan_id=plan_id,
            project_id=uuid4(),
            narration_track_id=uuid4(),
            output_path=Path("/tmp/roughcut.otio"),
            total_duration_ms=3000,
            timing_rate=1000,
            rough_cut_revision=1,
            narration_revision=1,
        )

    def export_jianying(
        self,
        plan_id: UUID,
        *,
        draft_name: str,
        settings: JianyingExportSettings,
    ) -> JianyingDraftArtifact:
        self.jianying_calls.append((plan_id, draft_name, settings))
        if self.jianying_error is not None:
            raise self.jianying_error
        return JianyingDraftArtifact(
            plan_id=plan_id,
            project_id=uuid4(),
            narration_track_id=uuid4(),
            draft_name=draft_name,
            output_path=(settings.draft_root / draft_name).resolve(),
            mode=settings.mode,
            backend_name="stub",
            backend_version="1",
            total_duration_ms=3000,
        )


def _app(service: StubExportService) -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)
    exports_router = import_module("clipatlas.api.routes.exports").router
    app.include_router(exports_router)
    app.state.export_service = service
    return app


def test_export_endpoints_call_only_export_service(tmp_path: Path, monkeypatch) -> None:
    service = StubExportService()
    app = _app(service)
    client = TestClient(app)
    plan_id = uuid4()
    draft_root = tmp_path / "drafts"
    monkeypatch.setenv("CLIPATLAS_JIANYING_DRAFT_ROOT", str(draft_root))
    monkeypatch.setenv("CLIPATLAS_JIANYING_MODE", "portable")

    otio_response = client.post(
        "/api/v1/exports/otio",
        json={"plan_id": str(plan_id)},
    )
    jianying_response = client.post(
        "/api/v1/exports/jianying",
        json={
            "plan_id": str(plan_id),
            "draft_name": "ClipAtlas Rough Cut",
            "width": 1280,
            "height": 720,
        },
    )

    assert otio_response.status_code == 200
    assert service.otio_calls == [plan_id]
    assert otio_response.json()["plan_id"] == str(plan_id)
    assert jianying_response.status_code == 200
    assert len(service.jianying_calls) == 1
    called_plan_id, draft_name, settings = service.jianying_calls[0]
    assert called_plan_id == plan_id
    assert draft_name == "ClipAtlas Rough Cut"
    assert settings.draft_root == draft_root
    assert settings.width == 1280
    assert settings.height == 720
    assert settings.mode == JianyingMode.PORTABLE


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (ExportPlanNotFoundError("missing"), 404, "export_plan_not_found"),
        (ExportNotReadyError("not ready"), 409, "export_not_ready"),
        (ExportInvariantError("invalid timeline"), 500, "export_invariant_failed"),
        (OtioSerializationError("write failed"), 500, "otio_serialization_failed"),
    ],
)
def test_otio_export_errors_have_stable_codes(
    error: Exception,
    status: int,
    code: str,
) -> None:
    client = TestClient(_app(StubExportService(otio_error=error)))

    response = client.post(
        "/api/v1/exports/otio",
        json={"plan_id": str(uuid4())},
    )

    assert response.status_code == status
    assert response.json()["error"]["code"] == code


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (JianyingUnavailableError("unavailable"), 503, "jianying_unavailable"),
        (JianyingDependencyError("missing dependency"), 503, "jianying_dependency_missing"),
        (JianyingMediaError("remote media"), 422, "jianying_media_unsupported"),
        (JianyingWriteError("write failed"), 500, "jianying_write_failed"),
    ],
)
def test_jianying_export_errors_have_stable_codes(
    tmp_path: Path,
    monkeypatch,
    error: Exception,
    status: int,
    code: str,
) -> None:
    monkeypatch.setenv("CLIPATLAS_JIANYING_DRAFT_ROOT", str(tmp_path / "drafts"))
    monkeypatch.setenv("CLIPATLAS_JIANYING_MODE", "portable")
    client = TestClient(_app(StubExportService(jianying_error=error)))

    response = client.post(
        "/api/v1/exports/jianying",
        json={"plan_id": str(uuid4()), "draft_name": "Draft"},
    )

    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def test_jianying_uses_default_draft_root(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("CLIPATLAS_JIANYING_DRAFT_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)
    service = StubExportService()
    client = TestClient(_app(service))

    response = client.post(
        "/api/v1/exports/jianying",
        json={"plan_id": str(uuid4()), "draft_name": "Draft"},
    )

    assert response.status_code == 200
    assert service.jianying_calls[0][2].draft_root == Path(
        DEFAULT_JIANYING_DRAFT_ROOT
    )


def test_successful_jianying_export_registers_generated_artifact(
    tmp_path: Path,
    monkeypatch,
) -> None:
    registry = GeneratedArtifactRegistry()
    app = _app(StubExportService())
    app.state.generated_artifact_registry = registry
    client = TestClient(app)
    plan_id = uuid4()
    draft_root = tmp_path / "drafts"
    monkeypatch.setenv("CLIPATLAS_JIANYING_DRAFT_ROOT", str(draft_root))
    monkeypatch.setenv("CLIPATLAS_JIANYING_MODE", "portable")

    response = client.post(
        "/api/v1/exports/jianying",
        json={"plan_id": str(plan_id), "draft_name": "Trusted Draft"},
    )

    assert response.status_code == 200
    registered = registry.get_jianying(plan_id)
    assert registered is not None
    assert registered.output_path == (draft_root / "Trusted Draft").resolve()


def test_failed_jianying_export_does_not_register_generated_artifact(
    tmp_path: Path,
    monkeypatch,
) -> None:
    registry = GeneratedArtifactRegistry()
    app = _app(StubExportService(jianying_error=JianyingWriteError("write failed")))
    app.state.generated_artifact_registry = registry
    client = TestClient(app)
    plan_id = uuid4()
    monkeypatch.setenv("CLIPATLAS_JIANYING_DRAFT_ROOT", str(tmp_path / "drafts"))
    monkeypatch.setenv("CLIPATLAS_JIANYING_MODE", "portable")

    response = client.post(
        "/api/v1/exports/jianying",
        json={"plan_id": str(plan_id), "draft_name": "Broken Draft"},
    )

    assert response.status_code == 500
    assert registry.get_jianying(plan_id) is None

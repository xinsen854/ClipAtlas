from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from clipatlas.api.routes.exports import router as exports_router
from clipatlas.exports.models import (
    JianyingDraftArtifact,
    JianyingExportSettings,
    OtioExportArtifact,
)


class RecordingExportService:
    def __init__(self) -> None:
        self.draft_names: list[str] = []

    def export_otio(self, plan_id: UUID) -> OtioExportArtifact:
        raise AssertionError(f"unexpected OTIO export: {plan_id}")

    def export_jianying(
        self,
        plan_id: UUID,
        *,
        draft_name: str,
        settings: JianyingExportSettings,
    ) -> JianyingDraftArtifact:
        self.draft_names.append(draft_name)
        return JianyingDraftArtifact(
            plan_id=plan_id,
            project_id=uuid4(),
            narration_track_id=uuid4(),
            draft_name=draft_name,
            output_path=(settings.draft_root / draft_name).resolve(),
            mode=settings.mode,
            backend_name="stub",
            backend_version="1",
            total_duration_ms=1000,
        )


def _client(service: RecordingExportService) -> TestClient:
    app = FastAPI()
    app.include_router(exports_router)
    app.state.export_service = service
    return TestClient(app)


@pytest.mark.parametrize(
    "draft_name",
    [
        "../escape", "..\\escape", "/tmp/escape", "C:\\escape",
        ".", "..", "C:", "CON", "NUL.txt", "COM1", "draft.", "draft ",
        " ", "draft:stream", "draft?", "draft\nname",
    ],
)
def test_jianying_export_rejects_path_like_draft_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    draft_name: str,
) -> None:
    service = RecordingExportService()
    client = _client(service)
    monkeypatch.setenv("CLIPATLAS_JIANYING_DRAFT_ROOT", str(tmp_path / "drafts"))
    monkeypatch.setenv("CLIPATLAS_JIANYING_MODE", "portable")

    response = client.post(
        "/api/v1/exports/jianying",
        json={"plan_id": str(uuid4()), "draft_name": draft_name},
    )

    assert response.status_code == 422
    assert service.draft_names == []


def test_jianying_export_accepts_chinese_and_spaces(tmp_path, monkeypatch):
    service = RecordingExportService()
    monkeypatch.setenv("CLIPATLAS_JIANYING_DRAFT_ROOT", str(tmp_path / "drafts"))
    monkeypatch.setenv("CLIPATLAS_JIANYING_MODE", "portable")
    response = _client(service).post(
        "/api/v1/exports/jianying",
        json={"plan_id": str(uuid4()), "draft_name": "泰钽700 首次验收"},
    )
    assert response.status_code == 200
    assert service.draft_names == ["泰钽700 首次验收"]

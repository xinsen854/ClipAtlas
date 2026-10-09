from pathlib import Path
from copy import deepcopy
from uuid import uuid4

import pytest

from clipatlas.exports.errors import TimelineExportError
from clipatlas.exports.models import JianyingExportSettings
from clipatlas.exports.service import TimelineExportService
from clipatlas.roughcut.store import RoughCutStore
from clipatlas.speech.store import NarrationStore

from tests.exports.test_finecut_service import _fixture


def test_export_success_returns_delivery_feedback(tmp_path: Path) -> None:
    plan, narration, _, rough_store, narration_store, finecut_store = _fixture(tmp_path)

    service = TimelineExportService(
        rough_cut_store=rough_store,
        narration_store=narration_store,
        finecut_timeline_store=finecut_store,
        export_root=tmp_path / "exports",
    )

    artifact = service.export_otio(plan.id)

    assert artifact.plan_id == plan.id
    assert artifact.project_id == plan.project_id
    assert artifact.narration_track_id == narration.id
    assert artifact.output_path.exists()
    assert artifact.total_duration_ms == plan.total_duration_ms
    assert artifact.rough_cut_revision == plan.revision


def test_export_failure_has_user_safe_error_boundary(tmp_path: Path) -> None:
    service = TimelineExportService(
        rough_cut_store=RoughCutStore(tmp_path / "rough.sqlite3"),
        narration_store=NarrationStore(tmp_path / "narration.sqlite3"),
        export_root=tmp_path / "exports",
    )

    with pytest.raises(TimelineExportError):
        service.export_otio(uuid4())


def test_jianying_dependency_missing_returns_export_error(tmp_path: Path) -> None:
    plan, _, _, rough_store, narration_store, _ = _fixture(tmp_path)

    service = TimelineExportService(
        rough_cut_store=rough_store,
        narration_store=narration_store,
        export_root=tmp_path / "exports",
        jianying_backend=None,
    )

    with pytest.raises(TimelineExportError) as exc_info:
        service.export_jianying(
            plan.id,
            draft_name="missing backend",
            settings=JianyingExportSettings(draft_root=tmp_path / "drafts"),
        )

    assert exc_info.type.__name__ == "JianyingUnavailableError"


def test_failed_export_does_not_mutate_timeline_document(tmp_path: Path) -> None:
    plan, _, document, rough_store, narration_store, finecut_store = _fixture(tmp_path)

    finecut_store.save(document)
    before_document = deepcopy(finecut_store.get(plan.project_id, plan.id))

    service = TimelineExportService(
        rough_cut_store=rough_store,
        narration_store=narration_store,
        finecut_timeline_store=finecut_store,
        export_root=tmp_path / "exports",
    )

    with pytest.raises(TimelineExportError):
        service.export_otio(uuid4())

    after_document = finecut_store.get(plan.project_id, plan.id)

    assert after_document == before_document

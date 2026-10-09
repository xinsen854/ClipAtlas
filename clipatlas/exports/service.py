from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from clipatlas.exports.contracts import JianyingBackend
from clipatlas.exports.errors import (
    ExportNotReadyError,
    ExportPlanNotFoundError,
    JianyingUnavailableError,
)
from clipatlas.exports.models import (
    JianyingDraftArtifact,
    JianyingExportSettings,
    OtioExportArtifact,
)
from clipatlas.exports.otio import OtioTimelineBuilder
from clipatlas.roughcut.models import RoughCutPlan
from clipatlas.roughcut.store import RoughCutStore
from clipatlas.speech.models import NarrationTrack
from clipatlas.speech.store import NarrationStore


class FineCutTimelineStoreLike(Protocol):
    def get(self, project_id: UUID, source_plan_id: UUID) -> Any | None: ...


class TimelineExportService:
    """Resolve persisted canonical data and orchestrate timeline exports."""

    def __init__(
        self,
        *,
        rough_cut_store: RoughCutStore,
        narration_store: NarrationStore,
        export_root: Path,
        otio_builder: OtioTimelineBuilder | None = None,
        jianying_backend: JianyingBackend | None = None,
        finecut_timeline_store: FineCutTimelineStoreLike | None = None,
    ) -> None:
        self._rough_cut_store = rough_cut_store
        self._narration_store = narration_store
        self._export_root = export_root.expanduser().resolve()
        self._otio_builder = otio_builder or OtioTimelineBuilder()
        self._jianying_backend = jianying_backend
        self._finecut_timeline_store = finecut_timeline_store

    def _load(self, plan_id: UUID) -> tuple[RoughCutPlan, NarrationTrack]:
        plan = self._rough_cut_store.get_plan(plan_id)
        if plan is None:
            raise ExportPlanNotFoundError(f"rough cut plan not found: {plan_id}")
        narration = self._narration_store.get_track(plan.narration_track_id)
        if narration is None:
            raise ExportNotReadyError(
                f"referenced narration track not found: {plan.narration_track_id}"
            )
        return plan, narration

    def _saved_finecut(self, plan: RoughCutPlan) -> Any | None:
        if self._finecut_timeline_store is None:
            return None
        return self._finecut_timeline_store.get(plan.project_id, plan.id)

    @staticmethod
    def _finecut_builder():
        # FineCut is an optional workspace package. Keep historical exports
        # importable when that package is not installed; load its bridge only
        # when a FineCut store is configured and actually contains a document.
        from clipatlas.integrations.finecut.export_roundtrip import FineCutOtioBuilder

        return FineCutOtioBuilder()

    def export_otio(self, plan_id: UUID) -> OtioExportArtifact:
        plan, narration = self._load(plan_id)
        finecut = self._saved_finecut(plan)
        if finecut is not None:
            builder = self._finecut_builder()
            timeline = builder.build(finecut, plan, narration)
            output_path = self._export_root / str(plan.project_id) / str(plan.id) / "finecut.otio"
            return builder.write_verified(
                timeline,
                output_path,
                plan_id=plan.id,
                project_id=plan.project_id,
                narration_track_id=plan.narration_track_id,
            )

        timeline = self._otio_builder.build(plan, narration)
        output_path = (
            self._export_root
            / str(plan.project_id)
            / str(plan.id)
            / f"roughcut-r{plan.revision}.otio"
        )
        return self._otio_builder.write_verified(
            timeline,
            output_path,
            plan_id=plan.id,
            project_id=plan.project_id,
            narration_track_id=plan.narration_track_id,
        )

    def export_jianying(
        self,
        plan_id: UUID,
        *,
        draft_name: str,
        settings: JianyingExportSettings,
    ) -> JianyingDraftArtifact:
        if self._jianying_backend is None:
            raise JianyingUnavailableError("Jianying backend is not available")

        plan, narration = self._load(plan_id)
        finecut = self._saved_finecut(plan)
        timeline = (
            self._finecut_builder().build(finecut, plan, narration)
            if finecut is not None
            else self._otio_builder.build(plan, narration)
        )
        return self._jianying_backend.export(
            timeline,
            draft_name=draft_name,
            settings=settings,
        )

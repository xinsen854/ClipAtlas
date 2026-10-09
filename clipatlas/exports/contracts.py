from typing import Protocol

import opentimelineio as otio  # type: ignore[import-untyped]

from clipatlas.exports.models import JianyingDraftArtifact, JianyingExportSettings


class JianyingBackend(Protocol):
    name: str
    version: str

    def export(
        self,
        timeline: otio.schema.Timeline,
        *,
        draft_name: str,
        settings: JianyingExportSettings,
    ) -> JianyingDraftArtifact: ...

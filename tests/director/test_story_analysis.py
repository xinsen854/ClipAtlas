from uuid import uuid4

import pytest

from clipatlas.director.story_errors import StoryOutlineConflictError
from clipatlas.director.story_models import (
    StoryAnalysisResult,
    StoryEvidenceItem,
    StoryEvidencePacket,
    StoryNodeDraft,
)
from clipatlas.director.story_service import StoryDirectorService
from clipatlas.director.story_store import StoryOutlineStore


class _EvidenceBuilder:
    def __init__(self, packet):
        self.packet = packet

    def build(self, project_id):
        assert project_id == self.packet.project_id
        return self.packet


class _Analyzer:
    def __init__(self, evidence_id):
        self.evidence_id = evidence_id

    async def analyze(self, skill, packet):
        return StoryAnalysisResult(
            summary="真实素材故事",
            nodes=[
                StoryNodeDraft(
                    title="开场",
                    summary="车辆驶入夜间山路。",
                    role="hook",
                    evidence_ids=[self.evidence_id],
                )
            ],
        )


def _packet():
    project_id = uuid4()
    evidence_id = f"visual:{uuid4()}:{uuid4()}"
    return StoryEvidencePacket(
        project_id=project_id,
        video_count=1,
        items=[
            StoryEvidenceItem(
                evidence_id=evidence_id,
                kind="visual",
                video_id=uuid4(),
                segment_id=uuid4(),
                start_ms=0,
                end_ms=1_000,
                text="车辆驶入夜间山路",
            )
        ],
    )


@pytest.mark.asyncio
async def test_analysis_accepts_provider_evid_label_only_for_a_real_project_evidence(tmp_path):
    packet = _packet()
    service = StoryDirectorService(
        evidence_builder=_EvidenceBuilder(packet),
        analyzer=_Analyzer(f"EVID:{packet.items[0].evidence_id}"),
        store=StoryOutlineStore(tmp_path / "story.sqlite3"),
    )

    outline = await service.analyze(
        packet.project_id,
        skill_name="story.md",
        skill_content="只使用真实证据",
    )

    assert outline.nodes[0].evidence[0].evidence_id == packet.items[0].evidence_id


@pytest.mark.asyncio
async def test_analysis_still_rejects_unknown_evidence_after_label_normalization(tmp_path):
    packet = _packet()
    service = StoryDirectorService(
        evidence_builder=_EvidenceBuilder(packet),
        analyzer=_Analyzer("EVID:visual:unknown"),
        store=StoryOutlineStore(tmp_path / "story.sqlite3"),
    )

    with pytest.raises(StoryOutlineConflictError):
        await service.analyze(
            packet.project_id,
            skill_name="story.md",
            skill_content="只使用真实证据",
        )

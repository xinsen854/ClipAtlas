from uuid import uuid4

from clipatlas.director.story_models import StoryEvidenceItem, StoryEvidencePacket
from clipatlas.director.story_service import StoryDirectorService
from clipatlas.director.story_store import StoryOutlineStore


class _ReadyEvidenceBuilder:
    def __init__(self, packet: StoryEvidencePacket) -> None:
        self.packet = packet

    def build(self, project_id):
        assert project_id == self.packet.project_id
        return self.packet


def test_readiness_summarizes_existing_project_evidence(tmp_path):
    project_id = uuid4()
    video_id = uuid4()
    packet = StoryEvidencePacket(
        project_id=project_id,
        video_count=1,
        items=[
            StoryEvidenceItem(
                evidence_id="visual:one",
                kind="visual",
                video_id=video_id,
                segment_id=uuid4(),
                start_ms=0,
                end_ms=1000,
                text="主人抱着猫进入诊室",
            ),
            StoryEvidenceItem(
                evidence_id="asr:one",
                kind="asr",
                video_id=video_id,
                start_ms=1000,
                end_ms=2000,
                text="医生开始检查",
            ),
        ],
        warnings=["一段 OCR 为空，已忽略"],
    )
    service = StoryDirectorService(
        evidence_builder=_ReadyEvidenceBuilder(packet),
        analyzer=None,
        store=StoryOutlineStore(tmp_path / "story.sqlite3"),
    )

    readiness = service.readiness(project_id)

    assert readiness.ready is True
    assert readiness.video_count == 1
    assert readiness.evidence_count == 2
    assert readiness.visual_count == 1
    assert readiness.asr_count == 1
    assert readiness.ocr_count == 0
    assert readiness.warnings == ["一段 OCR 为空，已忽略"]

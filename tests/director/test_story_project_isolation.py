from uuid import uuid4

import pytest

from clipatlas.director.story_errors import StoryOutlineNotFoundError
from clipatlas.director.story_models import (
    StoryEvidenceReference,
    StoryOutline,
    StoryOutlineEditNode,
    StoryOutlineNode,
)
from clipatlas.director.story_service import StoryDirectorService
from clipatlas.director.story_store import StoryOutlineStore


class _UnusedEvidenceBuilder:
    def build(self, project_id):  # pragma: no cover - edit/confirm must not rebuild evidence
        raise AssertionError("edit/confirm must not rebuild evidence")


class _UnusedAnalyzer:
    async def analyze(self, skill, packet):  # pragma: no cover - edit/confirm must not call provider
        raise AssertionError("edit/confirm must not call provider")


def _outline(project_id):
    evidence = StoryEvidenceReference(
        evidence_id="visual:test-segment",
        kind="visual",
        video_id=uuid4(),
        segment_id=uuid4(),
        start_ms=0,
        end_ms=1_000,
        text="主人抱着猫进入诊室",
        source_name="source.mp4",
    )
    node = StoryOutlineNode(
        order=0,
        title="进入诊室",
        summary="主人抱猫进入诊室。",
        role="setup",
        estimated_duration_ms=3_000,
        evidence=[evidence],
    )
    return StoryOutline(
        project_id=project_id,
        revision=1,
        skill_name="story.md",
        skill_hash="a" * 64,
        summary="素材中的真实事件",
        nodes=[node],
    )


def _service(tmp_path):
    store = StoryOutlineStore(tmp_path / "story.sqlite3")
    service = StoryDirectorService(
        evidence_builder=_UnusedEvidenceBuilder(),
        analyzer=_UnusedAnalyzer(),
        store=store,
    )
    return service, store


def test_edit_rejects_outline_owned_by_another_project(tmp_path):
    service, store = _service(tmp_path)
    owner_project_id = uuid4()
    current_project_id = uuid4()
    source = _outline(owner_project_id)
    store.save(source)

    edit = StoryOutlineEditNode(
        id=source.nodes[0].id,
        title="修改后的标题",
        summary="仍然只使用原证据。",
        role="setup",
        estimated_duration_ms=3_000,
    )

    with pytest.raises(StoryOutlineNotFoundError):
        service.edit(
            current_project_id,
            source.id,
            summary=source.summary,
            hook_rationale=source.hook_rationale,
            nodes=[edit],
        )


def test_confirm_rejects_outline_owned_by_another_project(tmp_path):
    service, store = _service(tmp_path)
    owner_project_id = uuid4()
    current_project_id = uuid4()
    source = _outline(owner_project_id)
    store.save(source)

    with pytest.raises(StoryOutlineNotFoundError):
        service.confirm(current_project_id, source.id)

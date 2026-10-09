from pathlib import Path
from uuid import uuid4

from clipatlas.exports.models import JianyingDraftArtifact, JianyingMode
from clipatlas.system.artifacts import GeneratedArtifactRegistry


def _artifact(output_path: Path) -> JianyingDraftArtifact:
    return JianyingDraftArtifact(
        plan_id=uuid4(),
        project_id=uuid4(),
        narration_track_id=uuid4(),
        draft_name="ClipAtlas Rough Cut",
        output_path=output_path,
        mode=JianyingMode.PORTABLE,
        backend_name="test",
        backend_version="1",
        total_duration_ms=5000,
    )


def test_registry_returns_only_artifact_registered_for_plan(tmp_path: Path) -> None:
    registry = GeneratedArtifactRegistry()
    artifact = _artifact(tmp_path / "drafts" / "ClipAtlas Rough Cut")

    registry.register_jianying(artifact)

    assert registry.get_jianying(artifact.plan_id) == artifact
    assert registry.get_jianying(uuid4()) is None

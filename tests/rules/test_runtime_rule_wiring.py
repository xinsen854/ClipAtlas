from pathlib import Path
from uuid import UUID

from clipatlas.app_state import build_narration_runtime, build_rough_cut_runtime
from clipatlas.rules.store import ProjectRuleStore
from clipatlas.speech.fake import FakeSpeechProvider
from clipatlas.speech.registry import SpeechProviderRegistry


class EmptySegmentSearch:
    async def search(
        self,
        query: str,
        limit: int = 10,
        video_ids: list[UUID] | None = None,
    ):
        return []


def test_runtime_builders_share_project_rule_store(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CLIPATLAS_NARRATION_ROOT", str(tmp_path / "narration"))
    monkeypatch.setenv("CLIPATLAS_ROUGHCUT_DB", str(tmp_path / "roughcut.sqlite3"))

    rule_store = ProjectRuleStore(tmp_path / "rules.sqlite3")
    registry = SpeechProviderRegistry()
    registry.register(FakeSpeechProvider())

    narration = build_narration_runtime(registry, rule_store=rule_store)
    assert narration.narration_service is not None
    assert narration.narration_service._rule_store is rule_store

    rough_cut = build_rough_cut_runtime(
        narration.store,
        EmptySegmentSearch(),
        rule_store=rule_store,
    )
    assert rough_cut.planner is not None
    assert rough_cut.planner._rule_store is rule_store

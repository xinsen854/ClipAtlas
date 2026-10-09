from pathlib import Path
from uuid import UUID

from clipatlas.app_state import RoughCutRuntime, build_rough_cut_runtime
from clipatlas.retrieval.search import SemanticSearchHit
from clipatlas.speech.audio import AudioNormalizer
from clipatlas.speech.store import NarrationStore


class FakeSearch:
    async def search(
        self,
        query: str,
        limit: int = 10,
        video_ids: list[UUID] | None = None,
    ) -> list[SemanticSearchHit]:
        return []


def test_runtime_with_semantic_search_contains_planner_and_store(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "roughcut.sqlite3"
    monkeypatch.setenv("CLIPATLAS_ROUGHCUT_DB", str(db_path))
    narration_store = NarrationStore(tmp_path / "narration.sqlite3")

    runtime = build_rough_cut_runtime(narration_store, FakeSearch())

    assert isinstance(runtime, RoughCutRuntime)
    assert runtime.planner is not None
    assert db_path.exists()


def test_runtime_without_semantic_search_keeps_store_but_disables_planner(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "roughcut.sqlite3"
    monkeypatch.setenv("CLIPATLAS_ROUGHCUT_DB", str(db_path))
    narration_store = NarrationStore(tmp_path / "narration.sqlite3")

    runtime = build_rough_cut_runtime(narration_store, None)

    assert runtime.planner is None
    assert db_path.exists()


def test_runtime_uses_configured_rough_cut_database_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "custom" / "plans.sqlite3"
    monkeypatch.setenv("CLIPATLAS_ROUGHCUT_DB", str(db_path))
    narration_store = NarrationStore(tmp_path / "narration.sqlite3")

    build_rough_cut_runtime(narration_store, None)

    assert db_path.exists()


def test_runtime_reuses_supplied_narration_store(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CLIPATLAS_ROUGHCUT_DB", str(tmp_path / "roughcut.sqlite3"))
    narration_store = NarrationStore(tmp_path / "narration.sqlite3")

    runtime = build_rough_cut_runtime(narration_store, FakeSearch())

    assert runtime.planner is not None
    assert runtime.planner._narration_store is narration_store


def test_runtime_wires_story_audio_materialization(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CLIPATLAS_ROUGHCUT_DB", str(tmp_path / "roughcut.sqlite3"))
    narration_store = NarrationStore(tmp_path / "narration.sqlite3")
    audio = AudioNormalizer()
    story_audio_root = tmp_path / "story-audio"

    runtime = build_rough_cut_runtime(
        narration_store,
        FakeSearch(),
        audio_normalizer=audio,
        story_audio_root=story_audio_root,
    )

    assert runtime.planner is not None
    assert runtime.planner._audio_normalizer is audio
    assert runtime.planner._story_audio_root == story_audio_root.resolve()

from pathlib import Path
from uuid import UUID, uuid4

import pytest

from clipatlas.domain.models import AnnotationOrigin, SemanticAnnotation
from clipatlas.retrieval.intent import RetrievalIntent
from clipatlas.retrieval.intent_search import IntentAwareHybridSearch
from clipatlas.retrieval.search import SemanticSearchHit
from clipatlas.roughcut.planner import RoughCutPlanner
from clipatlas.roughcut.store import RoughCutStore
from clipatlas.rules.models import ProjectRule, RuleKind
from clipatlas.rules.store import ProjectRuleStore
from clipatlas.speech.models import NarrationSourceMode, NarrationTrack, NarrationUnit, TimingQuality
from clipatlas.speech.store import NarrationStore


class RecordingIntentBuilder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object] | None]] = []

    async def build(
        self,
        source_text: str,
        context: dict[str, object] | None = None,
    ) -> RetrievalIntent:
        self.calls.append((source_text, context))
        return RetrievalIntent(source_text=source_text)


class RecordingSearch:
    def project_video_ids(self, project_id: UUID) -> list[UUID]:
        return [self._hit.video_id]

    def __init__(self, hit: SemanticSearchHit) -> None:
        self._hit = hit
        self.queries: list[str] = []

    async def search(
        self,
        query: str,
        limit: int = 10,
        video_ids: list[UUID] | None = None,
    ) -> list[SemanticSearchHit]:
        del video_ids
        self.queries.append(query)
        return [self._hit][:limit]


class ContextRecordingHybrid:
    def __init__(self) -> None:
        self.context_calls: list[tuple[str, dict[str, object] | None]] = []

    async def search(
        self,
        query: str,
        limit: int = 10,
        video_ids: list[UUID] | None = None,
    ) -> list[object]:
        del query, limit, video_ids
        raise AssertionError("plain hybrid search should not be used for contextual retrieval")

    async def search_with_context(
        self,
        query: str,
        *,
        context: dict[str, object] | None = None,
        limit: int = 10,
        video_ids: list[UUID] | None = None,
    ) -> list[object]:
        del limit, video_ids
        self.context_calls.append((query, context))
        return []


def _hit() -> SemanticSearchHit:
    segment_id = uuid4()
    annotation = SemanticAnnotation(
        segment_id=segment_id,
        origin=AnnotationOrigin.HUMAN,
        description="vehicle presented at a public launch",
        actions=["vehicle presentation"],
        confidence=0.95,
        verified=True,
    )
    return SemanticSearchHit(
        segment_id=segment_id,
        video_id=uuid4(),
        source_uri=f"file:///footage/{segment_id}.mp4",
        source_start_ms=1000,
        source_end_ms=5000,
        score=0.9,
        effective_description=annotation.description,
        annotation=annotation,
        embedding_provider="test",
        embedding_model="test-model",
        embedding_dimensions=3,
    )


def _narration(tmp_path: Path, project_id: UUID, text: str) -> NarrationStore:
    store = NarrationStore(tmp_path / f"narration-{project_id}.sqlite3")
    track = NarrationTrack(
        project_id=project_id,
        source_mode=NarrationSourceMode.TTS,
        script_hash="script",
        duration_ms=1000,
        timing_quality=TimingQuality.UNIT_EXACT,
        revision=1,
    )
    store.save_track(track)
    store.save_unit(
        NarrationUnit(
            track_id=track.id,
            sequence=0,
            text=text,
            text_hash="unit",
            start_ms=0,
            end_ms=1000,
        )
    )
    assert store.activate_track(project_id, track.id) is True
    return store


def _planner(
    tmp_path: Path,
    project_id: UUID,
    text: str,
    rule_store: ProjectRuleStore,
):
    builder = RecordingIntentBuilder()
    underlying = RecordingSearch(_hit())
    search = IntentAwareHybridSearch(search=underlying, builder=builder)
    planner = RoughCutPlanner(
        narration_store=_narration(tmp_path, project_id, text),
        search=search,
        store=RoughCutStore(tmp_path / f"roughcut-{project_id}.sqlite3"),
        rule_store=rule_store,
    )
    return planner, builder, underlying


@pytest.mark.asyncio
async def test_active_retrieval_rules_expand_query_and_pass_semantic_hints_without_mutating_beat(
    tmp_path: Path,
) -> None:
    project_id = uuid4()
    source = "Model 700 enters public view."
    rule_store = ProjectRuleStore(tmp_path / "rules.sqlite3")
    draft = rule_store.save_draft(
        project_id,
        [
            ProjectRule(
                kind=RuleKind.ENTITY_ALIAS,
                match="Model 700",
                replacement="flagship domestic off-road SUV",
            ),
            ProjectRule(
                kind=RuleKind.SEMANTIC_HINT,
                hint="prefer launch events and authoritative media coverage",
            ),
        ],
    )
    assert rule_store.activate(project_id, draft.revision) is not None

    planner, builder, underlying = _planner(tmp_path, project_id, source, rule_store)
    plan = await planner.create_plan(project_id)

    assert builder.calls == [
        (
            source,
            {
                "base_retrieval_query": (
                    "Model 700 enters public view. flagship domestic off-road SUV"
                ),
                "semantic_hints": [
                    "prefer launch events and authoritative media coverage"
                ],
                "rough_cut": True, "needed_duration_ms": 1000, "excluded_ranges": [],
                "narration_context": source,
                "minimum_shot_ms": 1000,
                "director_importance": None,
                "s_keywords": [],
                "allow_tail_text": True,
            },
        )
    ]
    assert underlying.queries == [
        "Model 700 enters public view. flagship domestic off-road SUV"
    ]
    assert plan.beats[0].query_text == source


@pytest.mark.asyncio
async def test_draft_retrieval_rules_do_not_affect_query_or_intent_context(tmp_path: Path) -> None:
    project_id = uuid4()
    source = "Model 700 enters public view."
    rule_store = ProjectRuleStore(tmp_path / "rules.sqlite3")
    rule_store.save_draft(
        project_id,
        [
            ProjectRule(
                kind=RuleKind.ENTITY_ALIAS,
                match="Model 700",
                replacement="flagship domestic off-road SUV",
            ),
            ProjectRule(kind=RuleKind.SEMANTIC_HINT, hint="prefer launch footage"),
        ],
    )

    planner, builder, underlying = _planner(tmp_path, project_id, source, rule_store)
    plan = await planner.create_plan(project_id)

    assert builder.calls == [(source, {"rough_cut": True, "needed_duration_ms": 1000,
        "excluded_ranges": [], "narration_context": source, "minimum_shot_ms": 1000,
        "director_importance": None, "s_keywords": [], "allow_tail_text": True})]
    assert underlying.queries == [source]
    assert plan.beats[0].query_text == source


@pytest.mark.asyncio
async def test_active_retrieval_rules_are_isolated_by_project(tmp_path: Path) -> None:
    project_a = uuid4()
    project_b = uuid4()
    source = "Model 700 enters public view."
    rule_store = ProjectRuleStore(tmp_path / "rules.sqlite3")
    draft = rule_store.save_draft(
        project_a,
        [
            ProjectRule(
                kind=RuleKind.ENTITY_ALIAS,
                match="Model 700",
                replacement="flagship domestic off-road SUV",
            )
        ],
    )
    assert rule_store.activate(project_a, draft.revision) is not None

    planner, builder, underlying = _planner(tmp_path, project_b, source, rule_store)
    await planner.create_plan(project_b)

    assert builder.calls == [(source, {"rough_cut": True, "needed_duration_ms": 1000,
        "excluded_ranges": [], "narration_context": source, "minimum_shot_ms": 1000,
        "director_importance": None, "s_keywords": [], "allow_tail_text": True})]
    assert underlying.queries == [source]

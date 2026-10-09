from pathlib import Path
from uuid import UUID, uuid4

import pytest

from clipatlas.domain.models import AnnotationOrigin, SemanticAnnotation
from clipatlas.retrieval.search import SemanticSearchHit
from clipatlas.roughcut.errors import (
    RoughCutConfigurationError,
    RoughCutRetrievalError,
    RoughCutTimingError,
)
from clipatlas.roughcut.planner import RoughCutPlanner
from clipatlas.roughcut.store import RoughCutStore
from clipatlas.speech.models import (
    NarrationSourceMode,
    NarrationTrack,
    NarrationUnit,
    TimingQuality,
)
from clipatlas.speech.store import NarrationStore


class FakeSearch:
    def project_video_ids(self, project_id: UUID) -> list[UUID]:
        return list({hit.video_id for hits in self.results.values() for hit in hits})

    def __init__(self, results: dict[str, list[SemanticSearchHit]]) -> None:
        self.results = results
        self.calls: list[tuple[str, int, list[UUID] | None]] = []

    async def search(
        self,
        query: str,
        limit: int = 10,
        video_ids: list[UUID] | None = None,
    ) -> list[SemanticSearchHit]:
        self.calls.append((query, limit, video_ids))
        return list(self.results.get(query, []))[:limit]


class EmptyProjectSearch(FakeSearch):
    def project_video_ids(self, project_id: UUID) -> list[UUID]:
        return []


@pytest.mark.asyncio
async def test_candidates_do_not_loop_or_overlap_to_fill_a_long_beat(tmp_path):
    narration_store, project, _ = _narration(tmp_path, [("一句", 0, 10000)], duration_ms=10000)
    video = uuid4()
    hits = [_hit(video_id=video, start_ms=0, end_ms=5000),
            _hit(video_id=video, start_ms=1000, end_ms=6000)]
    planner, store = _planner(tmp_path, narration_store, FakeSearch({"一句": hits}))
    plan = await planner.create_plan(project)
    assert plan.total_duration_ms == 10000
    assert plan.clips[-1].timeline_out_ms == 10000
    assert any(clip.schedule_level == "reuse" for clip in plan.clips)
    assert all(
        clip.timeline_out_ms - clip.timeline_in_ms >= 1500
        for clip in plan.clips
    )


def _hit(
    *,
    segment_id: UUID | None = None,
    video_id: UUID | None = None,
    source_uri: str = "file:///source.mp4",
    start_ms: int = 0,
    end_ms: int = 5000,
    score: float = 0.8,
    actions: list[str] | None = None,
) -> SemanticSearchHit:
    resolved_segment_id = segment_id or uuid4()
    annotation = SemanticAnnotation(
        segment_id=resolved_segment_id,
        origin=AnnotationOrigin.AI,
        description="素材",
        actions=actions or [],
        confidence=0.8,
    )
    return SemanticSearchHit(
        segment_id=resolved_segment_id,
        video_id=video_id or uuid4(),
        source_uri=source_uri,
        source_start_ms=start_ms,
        source_end_ms=end_ms,
        score=score,
        effective_description=annotation.description,
        annotation=annotation,
        embedding_provider="test",
        embedding_model="test-model",
        embedding_dimensions=3,
    )


def _narration(
    tmp_path: Path,
    units: list[tuple[str, int | None, int | None]],
    *,
    duration_ms: int,
    timing_quality: TimingQuality = TimingQuality.UNIT_EXACT,
) -> tuple[NarrationStore, UUID, NarrationTrack]:
    store = NarrationStore(tmp_path / f"narration-{uuid4()}.sqlite3")
    project_id = uuid4()
    track = NarrationTrack(
        project_id=project_id,
        source_mode=NarrationSourceMode.TTS,
        script_hash="script",
        duration_ms=duration_ms,
        timing_quality=timing_quality,
    )
    store.save_track(track)
    for sequence, (text, start_ms, end_ms) in enumerate(units):
        store.save_unit(
            NarrationUnit(
                track_id=track.id,
                sequence=sequence,
                text=text,
                text_hash=f"hash-{sequence}",
                start_ms=start_ms,
                end_ms=end_ms,
            )
        )
    assert store.activate_track(project_id, track.id) is True
    return store, project_id, track


def _planner(
    tmp_path: Path,
    narration_store: NarrationStore,
    search: FakeSearch,
) -> tuple[RoughCutPlanner, RoughCutStore]:
    rough_cut_store = RoughCutStore(tmp_path / f"roughcut-{uuid4()}.sqlite3")
    return (
        RoughCutPlanner(
            narration_store=narration_store,
            search=search,
            store=rough_cut_store,
        ),
        rough_cut_store,
    )


@pytest.mark.asyncio
async def test_every_beat_performs_top_k_semantic_search(tmp_path: Path) -> None:
    narration_store, project_id, _ = _narration(
        tmp_path,
        [("第一句", 0, 1000), ("第二句", 1000, 2000)],
        duration_ms=2000,
    )
    search = FakeSearch(
        {
            "第一句": [_hit()],
            "第二句": [_hit()],
        }
    )
    planner, _ = _planner(tmp_path, narration_store, search)

    await planner.create_plan(project_id)

    assert [call[:2] for call in search.calls] == [
        ("第一句", 12),
        ("第二句", 12),
    ]


@pytest.mark.asyncio
async def test_long_source_segment_is_trimmed_inside_canonical_bounds(tmp_path: Path) -> None:
    narration_store, project_id, _ = _narration(
        tmp_path,
        [("一句", 0, 1200)],
        duration_ms=1200,
    )
    hit = _hit(start_ms=5000, end_ms=10000)
    planner, _ = _planner(tmp_path, narration_store, FakeSearch({"一句": [hit]}))

    plan = await planner.create_plan(project_id)

    assert len(plan.clips) == 1
    clip = plan.clips[0]
    assert (clip.source_in_ms, clip.source_out_ms) == (5000, 6200)
    assert (clip.timeline_in_ms, clip.timeline_out_ms) == (0, 1200)
    assert hit.source_start_ms <= clip.source_in_ms < clip.source_out_ms <= hit.source_end_ms


@pytest.mark.asyncio
async def test_multiple_short_segments_fill_one_beat_without_timeline_gaps(tmp_path: Path) -> None:
    narration_store, project_id, _ = _narration(
        tmp_path,
        [("一句", 0, 8000)],
        duration_ms=8000,
    )
    hits = [
        _hit(start_ms=0, end_ms=4000),
        _hit(start_ms=5000, end_ms=9000),
        _hit(start_ms=10000, end_ms=14000),
    ]
    planner, _ = _planner(tmp_path, narration_store, FakeSearch({"一句": hits}))

    plan = await planner.create_plan(project_id)

    assert sum(clip.timeline_out_ms - clip.timeline_in_ms for clip in plan.clips) == 8000
    assert plan.clips[0].timeline_in_ms == 0
    assert plan.clips[-1].timeline_out_ms == 8000
    assert all(
        left.timeline_out_ms == right.timeline_in_ms
        for left, right in zip(plan.clips, plan.clips[1:], strict=False)
    )
    bounds = {hit.segment_id: (hit.source_start_ms, hit.source_end_ms) for hit in hits}
    assert all(
        bounds[clip.segment_id][0]
        <= clip.source_in_ms
        < clip.source_out_ms
        <= bounds[clip.segment_id][1]
        for clip in plan.clips
    )


@pytest.mark.asyncio
async def test_reuse_penalty_can_make_unused_segment_win_later_beat(tmp_path: Path) -> None:
    narration_store, project_id, _ = _narration(
        tmp_path,
        [("A", 0, 1000), ("B", 1000, 2000)],
        duration_ms=2000,
    )
    first_segment = UUID("00000000-0000-0000-0000-000000000001")
    second_segment = UUID("00000000-0000-0000-0000-000000000002")
    first = _hit(segment_id=first_segment, score=0.8)
    second = _hit(segment_id=second_segment, score=0.8)
    search = FakeSearch({"A": [second, first], "B": [second, first]})
    planner, _ = _planner(tmp_path, narration_store, search)

    plan = await planner.create_plan(project_id)

    assert [clip.segment_id for clip in plan.clips] == [first_segment, second_segment]
    assert plan.clips[1].score_breakdown.reuse_penalty == 0.0


@pytest.mark.asyncio
async def test_equal_scores_use_lexical_segment_uuid_tie_break(tmp_path: Path) -> None:
    narration_store, project_id, _ = _narration(
        tmp_path,
        [("一句", 0, 1000)],
        duration_ms=1000,
    )
    first_segment = UUID("00000000-0000-0000-0000-000000000001")
    second_segment = UUID("00000000-0000-0000-0000-000000000002")
    search = FakeSearch(
        {
            "一句": [
                _hit(segment_id=second_segment, score=0.8),
                _hit(segment_id=first_segment, score=0.8),
            ]
        }
    )
    planner, _ = _planner(tmp_path, narration_store, search)

    plan = await planner.create_plan(project_id)

    assert plan.clips[0].segment_id == first_segment


@pytest.mark.asyncio
async def test_missing_active_narration_is_configuration_error(tmp_path: Path) -> None:
    narration_store = NarrationStore(tmp_path / "narration.sqlite3")
    project_id = uuid4()
    planner, store = _planner(tmp_path, narration_store, FakeSearch({}))

    with pytest.raises(RoughCutConfigurationError):
        await planner.create_plan(project_id)

    assert store.next_plan_revision(project_id) == 1
    assert store.get_active_plan(project_id) is None


@pytest.mark.asyncio
async def test_track_only_narration_is_rejected(tmp_path: Path) -> None:
    narration_store, project_id, _ = _narration(
        tmp_path,
        [("一句", 0, 1000)],
        duration_ms=1000,
        timing_quality=TimingQuality.TRACK_ONLY,
    )
    planner, store = _planner(
        tmp_path,
        narration_store,
        FakeSearch({"一句": [_hit()]}),
    )

    with pytest.raises(RoughCutTimingError):
        await planner.create_plan(project_id)

    assert store.next_plan_revision(project_id) == 1
    assert store.get_active_plan(project_id) is None


@pytest.mark.asyncio
async def test_no_retrieval_hits_is_retrieval_error_and_does_not_persist(tmp_path: Path) -> None:
    narration_store, project_id, _ = _narration(
        tmp_path,
        [("一句", 0, 1000)],
        duration_ms=1000,
    )
    planner, store = _planner(tmp_path, narration_store, FakeSearch({"一句": []}))

    with pytest.raises(RoughCutRetrievalError):
        await planner.create_plan(project_id)

    assert store.next_plan_revision(project_id) == 1
    assert store.get_active_plan(project_id) is None


@pytest.mark.asyncio
async def test_plan_covers_exact_narration_timeline_and_is_activated(tmp_path: Path) -> None:
    narration_store, project_id, track = _narration(
        tmp_path,
        [("第一句", 200, 1000), ("第二句", 1400, 2200)],
        duration_ms=2500,
    )
    search = FakeSearch(
        {
            "第一句": [_hit(end_ms=5000)],
            "第二句": [_hit(end_ms=5000)],
        }
    )
    planner, store = _planner(tmp_path, narration_store, search)

    plan = await planner.create_plan(project_id)

    assert plan.total_duration_ms == track.duration_ms == 2500
    assert plan.clips[0].timeline_in_ms == 0
    assert plan.clips[-1].timeline_out_ms == 2500
    assert all(
        left.timeline_out_ms == right.timeline_in_ms
        for left, right in zip(plan.clips, plan.clips[1:], strict=False)
    )
    assert store.get_active_plan(project_id) == plan
    assert store.get_plan(plan.id) == plan


@pytest.mark.asyncio
async def test_video_filter_is_forwarded_unchanged_to_every_search(tmp_path: Path) -> None:
    narration_store, project_id, _ = _narration(
        tmp_path,
        [("第一句", 0, 500), ("第二句", 500, 1000)],
        duration_ms=1000,
    )
    video_ids = [uuid4(), uuid4()]
    search = FakeSearch({"第一句": [_hit(video_id=video_ids[0])],
                         "第二句": [_hit(video_id=video_ids[1])]})
    planner, _ = _planner(tmp_path, narration_store, search)

    await planner.create_plan(project_id, video_ids=video_ids)

    assert [call[2] for call in search.calls] == [video_ids, video_ids]


@pytest.mark.asyncio
async def test_empty_new_project_never_falls_back_to_the_whole_library(tmp_path: Path) -> None:
    narration_store, project_id, _ = _narration(
        tmp_path, [("一句", 0, 1000)], duration_ms=1000,
    )
    search = EmptyProjectSearch({"一句": [_hit()]})
    planner, _ = _planner(tmp_path, narration_store, search)

    with pytest.raises(RoughCutRetrievalError):
        await planner.create_plan(project_id)

    assert search.calls == [("一句", 12, [])]


@pytest.mark.asyncio
async def test_explicit_foreign_ids_and_out_of_scope_search_results_are_excluded(tmp_path):
    narration_store, project_id, _ = _narration(
        tmp_path, [("一句", 0, 1000)], duration_ms=1000,
    )
    own, foreign = _hit(), _hit(score=1)
    search = FakeSearch({"一句": [foreign, own]})
    search.project_video_ids = lambda _: [own.video_id]
    planner, store = _planner(tmp_path, narration_store, search)
    plan = await planner.create_plan(project_id, video_ids=[foreign.video_id, own.video_id])
    assert search.calls == [("一句", 12, [own.video_id])]
    assert {clip.video_id for clip in plan.clips} == {own.video_id}
    assert store.get_plan(plan.id).quality_report is not None


@pytest.mark.asyncio
async def test_explicit_top_k_is_used_and_persisted_in_plan_settings(tmp_path: Path) -> None:
    narration_store, project_id, _ = _narration(
        tmp_path,
        [("一句", 0, 1000)],
        duration_ms=1000,
    )
    search = FakeSearch({"一句": [_hit()]})
    planner, _ = _planner(tmp_path, narration_store, search)

    plan = await planner.create_plan(project_id, top_k=7)

    assert search.calls == [("一句", 7, search.project_video_ids(project_id))]
    assert plan.settings.top_k == 7


@pytest.mark.asyncio
async def test_same_inputs_produce_same_source_choice_order(tmp_path: Path) -> None:
    narration_store, project_id, _ = _narration(
        tmp_path,
        [("第一句", 0, 1000), ("第二句", 1000, 2000)],
        duration_ms=2000,
    )
    first_segment = UUID("00000000-0000-0000-0000-000000000001")
    second_segment = UUID("00000000-0000-0000-0000-000000000002")
    results = {
        "第一句": [
            _hit(segment_id=second_segment, score=0.8),
            _hit(segment_id=first_segment, score=0.8),
        ],
        "第二句": [
            _hit(segment_id=second_segment, score=0.8),
            _hit(segment_id=first_segment, score=0.8),
        ],
    }
    planner, _ = _planner(tmp_path, narration_store, FakeSearch(results))

    first_plan = await planner.create_plan(project_id)
    second_plan = await planner.create_plan(project_id)

    assert [clip.segment_id for clip in first_plan.clips] == [
        clip.segment_id for clip in second_plan.clips
    ]
    assert second_plan.revision == first_plan.revision + 1


def test_generic_fallback_survives_director_reject() -> None:
    """Generic/source fallback shots must never be dropped by the S/A hard filter."""
    from types import SimpleNamespace

    from clipatlas.director.models import DirectorUnit

    unit = DirectorUnit(
        text_range="大梁结构",
        importance="S",
        topic="大梁",
        required_objects=["大梁"],
        avoid=["座椅"],
    )
    generic = SimpleNamespace(
        segment_id=uuid4(),
        schedule_level="generic",
        annotation=SemanticAnnotation(
            segment_id=uuid4(),
            origin=AnnotationOrigin.AI,
            description="座椅特写（与需求无关的中性画面）",
            confidence=0.0,
        ),
    )
    plain = SimpleNamespace(
        segment_id=uuid4(),
        schedule_level="exact",
        annotation=SemanticAnnotation(
            segment_id=uuid4(),
            origin=AnnotationOrigin.AI,
            description="座椅特写",
            confidence=0.9,
        ),
    )
    kept = RoughCutPlanner._reject_director_mismatches([generic, plain], [unit], [])
    assert [getattr(hit, "schedule_level", "exact") for hit in kept] == ["generic"]

@pytest.mark.asyncio
async def test_confirmed_story_outline_preserves_visual_only_execution_window(
    tmp_path: Path,
) -> None:
    """A 0-unit story node must own program time without fake narration."""
    from datetime import UTC, datetime

    from clipatlas.director.story_models import (
        StoryEvidenceReference,
        StoryOutline,
        StoryOutlineNode,
    )
    from clipatlas.integrations.finecut.narration_bridge import narration_reference
    from clipatlas.roughcut.models import RoughCutPlan

    narration_store = NarrationStore(tmp_path / "visual-only-narration.sqlite3")
    project_id = uuid4()
    track = NarrationTrack(
        project_id=project_id,
        source_mode=NarrationSourceMode.IMPORTED,
        script_hash="node-b-script",
        script="Node B narration",
        audio_uri=(tmp_path / "prepared-7000ms.wav").resolve().as_uri(),
        duration_ms=7000,
        timing_quality=TimingQuality.UNIT_EXACT,
    )
    narration_store.save_track(track)
    node_b_unit = NarrationUnit(
        track_id=track.id,
        sequence=0,
        text="Node B narration",
        text_hash="node-b-hash",
        start_ms=3000,
        end_ms=7000,
        source=NarrationSourceMode.IMPORTED,
    )
    narration_store.save_unit(node_b_unit)
    assert narration_store.activate_track(project_id, track.id) is True

    visual_evidence = StoryEvidenceReference(
        evidence_id="visual:node-a",
        kind="visual",
        video_id=uuid4(),
        segment_id=uuid4(),
        start_ms=10_000,
        end_ms=18_000,
        text="A visual-only opening",
        source_name="visual-a.mp4",
    )
    narration_evidence = StoryEvidenceReference(
        evidence_id="asr:node-b",
        kind="asr",
        video_id=uuid4(),
        start_ms=20_000,
        end_ms=24_000,
        text="Node B narration",
        source_name="spoken-b.mp4",
    )
    node_a = StoryOutlineNode(
        order=0,
        title="Visual opening",
        summary="A visual-only opening",
        role="hook",
        estimated_duration_ms=3000,
        evidence=[visual_evidence],
    )
    node_b = StoryOutlineNode(
        order=1,
        title="Narrated continuation",
        summary="Node B narration",
        role="development",
        estimated_duration_ms=4000,
        evidence=[narration_evidence],
    )
    outline = StoryOutline(
        project_id=project_id,
        revision=1,
        skill_name="test-story-skill",
        skill_hash="a" * 64,
        summary="Visual opening followed by narration.",
        nodes=[node_a, node_b],
        status="confirmed",
        confirmed_at=datetime.now(UTC),
    )

    hit = _hit(start_ms=30_000, end_ms=40_000)

    class AnyQuerySearch(FakeSearch):
        async def search(self, query, limit=10, video_ids=None):
            self.calls.append((query, limit, video_ids))
            return [hit]

    planner, _ = _planner(
        tmp_path,
        narration_store,
        AnyQuerySearch({"fixture": [hit]}),
    )

    plan = await planner.create_plan(
        project_id,
        story_outline=outline,
        story_node_narration_unit_ids={
            node_a.id: [],
            node_b.id: [node_b_unit.id],
        },
    )

    assert isinstance(plan, RoughCutPlan)
    assert plan.total_duration_ms == 7000

    ordered_clips = sorted(plan.clips, key=lambda clip: clip.timeline_in_ms)
    node_a_clips = [clip for clip in ordered_clips if clip.timeline_out_ms <= 3000]
    node_b_clips = [clip for clip in ordered_clips if clip.timeline_in_ms >= 3000]
    assert node_a_clips
    assert node_b_clips
    assert node_a_clips[0].timeline_in_ms == 0
    assert node_a_clips[-1].timeline_out_ms == 3000
    assert node_b_clips[0].timeline_in_ms == 3000
    assert node_b_clips[-1].timeline_out_ms == 7000

    stored_units = narration_store.list_units(track.id)
    assert [unit.id for unit in stored_units] == [node_b_unit.id]
    assert [
        beat.text for beat in plan.beats if beat.text.strip()
    ] == ["Node B narration"]
    assert [
        (subtitle.text, subtitle.start_ms, subtitle.end_ms)
        for subtitle in plan.subtitles
    ] == [("Node B narration", 3000, 7000)]

    narration = narration_reference(track, plan.beats)
    assert [
        (segment.text, segment.start_ms, segment.end_ms)
        for segment in narration.segments
    ] == [("Node B narration", 3000, 7000)]


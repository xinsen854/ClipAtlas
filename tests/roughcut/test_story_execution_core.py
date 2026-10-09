from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname
from uuid import UUID, uuid4

import pytest

from clipatlas.director.story_models import (
    StoryEvidenceReference,
    StoryOutline,
    StoryOutlineNode,
)
from clipatlas.domain.models import AnnotationOrigin, SemanticAnnotation
from clipatlas.integrations.finecut.narration_bridge import narration_reference
from clipatlas.retrieval.search import SemanticSearchHit
from clipatlas.roughcut.planner import RoughCutPlanner
from clipatlas.roughcut.store import RoughCutStore
from clipatlas.speech.models import (
    NarrationSourceMode,
    NarrationTrack,
    NarrationUnit,
    TimingQuality,
)
from clipatlas.speech.store import NarrationStore


class StorySearch:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.parse_calls = 0
        self._hits = [self._hit(index) for index in range(8)]

    @staticmethod
    def _hit(index: int) -> SemanticSearchHit:
        segment_id = uuid4()
        annotation = SemanticAnnotation(
            segment_id=segment_id,
            origin=AnnotationOrigin.AI,
            description=f"story material {index}",
            confidence=0.9,
        )
        return SemanticSearchHit(
            segment_id=segment_id,
            video_id=uuid4(),
            source_uri=f"file:///story-{index}.mp4",
            source_start_ms=0,
            source_end_ms=12_000,
            score=0.9 - index * 0.01,
            effective_description=annotation.description,
            annotation=annotation,
            embedding_provider="test",
            embedding_model="test-model",
            embedding_dimensions=3,
        )

    def project_video_ids(self, project_id: UUID) -> list[UUID]:
        return [hit.video_id for hit in self._hits]

    async def search(
        self,
        query: str,
        limit: int = 10,
        video_ids: list[UUID] | None = None,
    ) -> list[SemanticSearchHit]:
        self.calls.append(query)
        allowed = set(video_ids or [hit.video_id for hit in self._hits])
        return [hit for hit in self._hits if hit.video_id in allowed][:limit]

    def parse_video(self, *args, **kwargs):  # pragma: no cover - must never be called
        self.parse_calls += 1
        raise AssertionError("rough-cut story execution must not re-parse video")


class FakeAudioNormalizer:
    def __init__(self) -> None:
        self.durations: dict[Path, int] = {}
        self.extract_calls: list[tuple[int, int]] = []
        self.silence_calls: list[int] = []
        self.concat_calls: list[list[Path]] = []

    @staticmethod
    def _write(path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"wav")
        return path

    async def extract(
        self,
        source: Path,
        destination: Path,
        *,
        start_ms: int,
        end_ms: int,
        sample_rate: int = 48_000,
    ) -> Path:
        assert source.is_file()
        self.extract_calls.append((start_ms, end_ms))
        self.durations[destination.resolve()] = end_ms - start_ms
        return self._write(destination)

    async def silence(
        self,
        destination: Path,
        *,
        duration_ms: int,
        sample_rate: int = 48_000,
    ) -> Path:
        self.silence_calls.append(duration_ms)
        self.durations[destination.resolve()] = duration_ms
        return self._write(destination)

    async def concat(self, inputs: list[Path], destination: Path) -> Path:
        self.concat_calls.append(list(inputs))
        self.durations[destination.resolve()] = sum(
            self.durations[path.resolve()] for path in inputs
        )
        return self._write(destination)

    async def probe_duration_ms(self, source: Path) -> int:
        return self.durations[source.resolve()]


def _story_fixture(
    tmp_path: Path,
    spec: list[tuple[str, int]],
) -> tuple[
    NarrationStore,
    UUID,
    NarrationTrack,
    StoryOutline,
    dict[UUID, list[UUID]],
]:
    narration_store = NarrationStore(tmp_path / f"narration-{uuid4()}.sqlite3")
    project_id = uuid4()
    narration_duration = sum(duration for kind, duration in spec if kind == "narration")
    script_parts = [f"Narration {index}" for index, (kind, _) in enumerate(spec) if kind == "narration"]
    script = "。".join(script_parts)
    source_audio = tmp_path / f"source-{uuid4()}.wav"
    audio_uri: str | None = None
    if narration_duration:
        source_audio.write_bytes(b"prepared-audio")
        audio_uri = source_audio.resolve().as_uri()
    track = NarrationTrack(
        project_id=project_id,
        source_mode=NarrationSourceMode.IMPORTED,
        script_hash=sha256(script.encode("utf-8")).hexdigest(),
        script=script or None,
        audio_uri=audio_uri,
        duration_ms=narration_duration,
        timing_quality=TimingQuality.UNIT_EXACT,
    )
    narration_store.save_track(track)

    nodes: list[StoryOutlineNode] = []
    mapping: dict[UUID, list[UUID]] = {}
    source_cursor = 0
    narration_sequence = 0
    for order, (kind, duration_ms) in enumerate(spec):
        evidence = StoryEvidenceReference(
            evidence_id=f"{kind}:{order}",
            kind="visual" if kind == "visual_only" else "asr",
            video_id=uuid4(),
            segment_id=uuid4() if kind == "visual_only" else None,
            start_ms=20_000 + order * 10_000,
            end_ms=24_000 + order * 10_000,
            text=f"Evidence {order}",
            source_name=f"source-{order}.mp4",
        )
        node = StoryOutlineNode(
            order=order,
            title=f"Node {order}",
            summary=f"Story node {order}",
            role="hook" if order == 0 else "development",
            estimated_duration_ms=duration_ms,
            evidence=[evidence],
        )
        nodes.append(node)
        if kind == "narration":
            unit = NarrationUnit(
                track_id=track.id,
                sequence=narration_sequence,
                text=f"Narration {order}",
                text_hash=f"unit-{order}",
                start_ms=source_cursor,
                end_ms=source_cursor + duration_ms,
                source=NarrationSourceMode.IMPORTED,
            )
            narration_store.save_unit(unit)
            mapping[node.id] = [unit.id]
            narration_sequence += 1
            source_cursor += duration_ms
        else:
            mapping[node.id] = []

    assert narration_store.activate_track(project_id, track.id)
    outline = StoryOutline(
        project_id=project_id,
        revision=3,
        skill_name="phase-b2-test",
        skill_hash="b" * 64,
        summary="Phase B2 execution fixture",
        nodes=nodes,
        status="confirmed",
        confirmed_at=datetime.now(UTC),
    )
    return narration_store, project_id, track, outline, mapping


def _planner(
    tmp_path: Path,
    narration_store: NarrationStore,
    search: StorySearch,
    audio: FakeAudioNormalizer,
) -> tuple[RoughCutPlanner, RoughCutStore]:
    store = RoughCutStore(tmp_path / f"roughcut-{uuid4()}.sqlite3")
    planner = RoughCutPlanner(
        narration_store=narration_store,
        search=search,
        store=store,
        audio_normalizer=audio,
        story_audio_root=tmp_path / "narration-audio",
    )
    return planner, store


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        (
            [("visual_only", 3000), ("narration", 2000)],
            [("visual_only", 0, 3000), ("narration", 3000, 5000)],
        ),
        (
            [("narration", 2000), ("visual_only", 3000)],
            [("narration", 0, 2000), ("visual_only", 2000, 5000)],
        ),
        (
            [("visual_only", 1500), ("narration", 2000), ("visual_only", 2500)],
            [
                ("visual_only", 0, 1500),
                ("narration", 1500, 3500),
                ("visual_only", 3500, 6000),
            ],
        ),
        (
            [("visual_only", 1500), ("visual_only", 2500)],
            [("visual_only", 0, 1500), ("visual_only", 1500, 4000)],
        ),
        (
            [
                ("narration", 1000),
                ("visual_only", 1500),
                ("visual_only", 2500),
                ("narration", 2000),
            ],
            [
                ("narration", 0, 1000),
                ("visual_only", 1000, 2500),
                ("visual_only", 2500, 5000),
                ("narration", 5000, 7000),
            ],
        ),
    ],
)
async def test_story_program_windows_cover_visual_and_narration_without_gaps(
    tmp_path: Path,
    spec: list[tuple[str, int]],
    expected: list[tuple[str, int, int]],
) -> None:
    narration_store, project_id, _, outline, mapping = _story_fixture(tmp_path, spec)
    search = StorySearch()
    audio = FakeAudioNormalizer()
    planner, _ = _planner(tmp_path, narration_store, search, audio)

    plan = await planner.create_plan(
        project_id,
        story_outline=outline,
        story_node_narration_unit_ids=mapping,
    )

    assert [
        (beat.kind, beat.timeline_start_ms, beat.timeline_end_ms)
        for beat in plan.beats
    ] == expected
    assert plan.beats[0].timeline_start_ms == 0
    assert plan.beats[-1].timeline_end_ms == plan.total_duration_ms
    assert all(
        left.timeline_end_ms == right.timeline_start_ms
        for left, right in zip(plan.beats, plan.beats[1:], strict=False)
    )
    assert search.parse_calls == 0


def test_story_beats_carry_full_node_evidence_into_retrieval_intent(tmp_path: Path) -> None:
    narration_store, _, track, outline, mapping = _story_fixture(
        tmp_path,
        [("visual_only", 3000), ("narration", 2000)],
    )

    beats = RoughCutPlanner._build_story_beats(
        track,
        narration_store.list_units(track.id),
        outline,
        mapping,
    )

    for beat, node in zip(beats, outline.nodes, strict=True):
        assert beat.retrieval_intent["story_evidence"] == [
            item.model_dump(mode="json") for item in node.evidence
        ]
        assert beat.retrieval_intent["story_role"] == node.role


@pytest.mark.asyncio
async def test_visual_only_node_between_multimodal_nodes_keeps_its_program_window(
    tmp_path: Path,
) -> None:
    narration_store, project_id, track, outline, mapping = _story_fixture(
        tmp_path,
        [("narration", 2_000), ("visual_only", 3_000), ("narration", 2_000)],
    )
    multimodal_nodes = []
    for node in (outline.nodes[0], outline.nodes[2]):
        multimodal_nodes.append(node.model_copy(update={
            "evidence": [
                StoryEvidenceReference(
                    evidence_id=f"visual:{node.id}",
                    kind="visual",
                    video_id=node.evidence[0].video_id,
                    segment_id=uuid4(),
                    start_ms=node.evidence[0].start_ms,
                    end_ms=node.evidence[0].end_ms,
                    text=f"Visual evidence for {node.title}",
                ),
                *node.evidence,
            ],
        }))
    outline = outline.model_copy(update={
        "nodes": [multimodal_nodes[0], outline.nodes[1], multimodal_nodes[1]],
    })
    search = StorySearch()
    audio = FakeAudioNormalizer()
    planner, _ = _planner(tmp_path, narration_store, search, audio)

    plan = await planner.create_plan(
        project_id,
        story_outline=outline,
        story_node_narration_unit_ids=mapping,
    )

    assert [[item.kind for item in node.evidence] for node in outline.nodes] == [
        ["visual", "asr"],
        ["visual"],
        ["visual", "asr"],
    ]
    assert [
        (beat.kind, beat.text, beat.timeline_start_ms, beat.timeline_end_ms)
        for beat in plan.beats
    ] == [
        ("narration", "Narration 0", 0, 2_000),
        ("visual_only", "", 2_000, 5_000),
        ("narration", "Narration 2", 5_000, 7_000),
    ]
    final_units = narration_store.list_units(plan.narration_track_id)
    assert [(unit.start_ms, unit.end_ms) for unit in final_units] == [
        (0, 2_000),
        (5_000, 7_000),
    ]
    assert audio.silence_calls == [3_000]
    assert audio.extract_calls == [(0, 2_000), (2_000, 4_000)]


@pytest.mark.asyncio
async def test_story_visual_only_windows_insert_silence_and_retime_narration_units(
    tmp_path: Path,
) -> None:
    spec = [
        ("narration", 2000),
        ("visual_only", 3000),
        ("narration", 2000),
    ]
    narration_store, project_id, source_track, outline, mapping = _story_fixture(tmp_path, spec)
    search = StorySearch()
    audio = FakeAudioNormalizer()
    planner, _ = _planner(tmp_path, narration_store, search, audio)

    plan = await planner.create_plan(
        project_id,
        story_outline=outline,
        story_node_narration_unit_ids=mapping,
    )

    assert plan.total_duration_ms == 7000
    assert plan.narration_track_id != source_track.id
    final_track = narration_store.get_track(plan.narration_track_id)
    assert final_track is not None
    assert final_track.duration_ms == plan.total_duration_ms
    assert final_track.audio_uri is not None
    parsed = urlparse(final_track.audio_uri)
    final_audio = Path(url2pathname(parsed.path))
    assert await audio.probe_duration_ms(final_audio) == plan.total_duration_ms
    assert audio.silence_calls == [3000]
    assert audio.extract_calls == [(0, 2000), (2000, 4000)]

    final_units = narration_store.list_units(final_track.id)
    assert [(unit.start_ms, unit.end_ms) for unit in final_units] == [
        (0, 2000),
        (5000, 7000),
    ]
    assert [beat.text for beat in plan.beats if beat.kind == "narration"] == [
        "Narration 0",
        "Narration 2",
    ]
    assert [(item.start_ms, item.end_ms) for item in plan.subtitles] == [
        (0, 2000),
        (5000, 7000),
    ]

    narration = narration_reference(final_track, plan.beats)
    assert [(segment.start_ms, segment.end_ms) for segment in narration.segments] == [
        (0, 2000),
        (5000, 7000),
    ]


@pytest.mark.asyncio
async def test_all_visual_story_has_full_silence_track_without_fake_units_or_subtitles(
    tmp_path: Path,
) -> None:
    spec = [("visual_only", 1200), ("visual_only", 1800)]
    narration_store, project_id, source_track, outline, mapping = _story_fixture(tmp_path, spec)
    search = StorySearch()
    audio = FakeAudioNormalizer()
    planner, _ = _planner(tmp_path, narration_store, search, audio)

    plan = await planner.create_plan(
        project_id,
        story_outline=outline,
        story_node_narration_unit_ids=mapping,
    )

    assert plan.total_duration_ms == 3000
    assert plan.narration_track_id != source_track.id
    final_track = narration_store.get_track(plan.narration_track_id)
    assert final_track is not None
    assert final_track.duration_ms == 3000
    assert narration_store.list_units(final_track.id) == []
    assert plan.subtitles == []
    assert [beat.kind for beat in plan.beats] == ["visual_only", "visual_only"]
    assert narration_reference(final_track, plan.beats).segments == []
    assert audio.silence_calls == [1200, 1800]


@pytest.mark.asyncio
async def test_story_with_only_unit_audio_is_materialized_by_existing_planner(
    tmp_path: Path,
) -> None:
    narration_store, project_id, source_track, outline, mapping = _story_fixture(
        tmp_path,
        [("narration", 2_000)],
    )
    source_track = source_track.model_copy(update={"audio_uri": None})
    narration_store.save_track(source_track)
    source_unit = narration_store.list_units(source_track.id)[0]
    unit_audio = tmp_path / "original-audio-unit.wav"
    unit_audio.write_bytes(b"prepared-audio")
    narration_store.save_unit(source_unit.model_copy(update={
        "audio_uri": unit_audio.resolve().as_uri(),
    }))
    search = StorySearch()
    audio = FakeAudioNormalizer()
    planner, _ = _planner(tmp_path, narration_store, search, audio)

    plan = await planner.create_plan(
        project_id,
        narration_track_id=source_track.id,
        story_outline=outline,
        story_node_narration_unit_ids=mapping,
    )

    assert plan.narration_track_id != source_track.id
    assert audio.extract_calls == [(0, 2_000)]
    assert narration_store.get_track(plan.narration_track_id).audio_uri is not None


@pytest.mark.asyncio
async def test_story_provenance_round_trips_with_existing_roughcut_store(
    tmp_path: Path,
) -> None:
    narration_store, project_id, _, outline, mapping = _story_fixture(
        tmp_path,
        [("visual_only", 1500), ("narration", 2000)],
    )
    search = StorySearch()
    audio = FakeAudioNormalizer()
    planner, store = _planner(tmp_path, narration_store, search, audio)

    plan = await planner.create_plan(
        project_id,
        story_outline=outline,
        story_node_narration_unit_ids=mapping,
    )
    reloaded = store.get_plan(plan.id)

    assert reloaded is not None
    assert reloaded.story_provenance == plan.story_provenance
    provenance = reloaded.story_provenance
    assert provenance is not None
    assert provenance["outline_id"] == str(outline.id)
    assert provenance["outline_revision"] == outline.revision
    executed = provenance["executed_nodes"]
    assert len(executed) == 2
    assert [node["story_node_id"] for node in executed] == [
        str(node.id) for node in outline.nodes
    ]
    assert [node["story_order"] for node in executed] == [0, 1]
    assert all(node["beat_ids"] for node in executed)
    assert all(node["clips"] for node in executed)
    assert executed[0]["evidence"] == [
        {
            "evidence_id": outline.nodes[0].evidence[0].evidence_id,
            "start_ms": outline.nodes[0].evidence[0].start_ms,
            "end_ms": outline.nodes[0].evidence[0].end_ms,
        }
    ]


@pytest.mark.asyncio
async def test_traditional_roughcut_does_not_enter_story_audio_or_provenance_path(
    tmp_path: Path,
) -> None:
    narration_store, project_id, source_track, _, _ = _story_fixture(
        tmp_path,
        [("narration", 2000), ("narration", 2000)],
    )
    search = StorySearch()
    audio = FakeAudioNormalizer()
    planner, _ = _planner(tmp_path, narration_store, search, audio)

    plan = await planner.create_plan(project_id)

    assert plan.narration_track_id == source_track.id
    assert plan.total_duration_ms == 4000
    assert plan.story_provenance is None
    assert audio.extract_calls == []
    assert audio.silence_calls == []
    assert audio.concat_calls == []
    assert search.parse_calls == 0

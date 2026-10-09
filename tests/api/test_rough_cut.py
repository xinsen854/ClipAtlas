from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from clipatlas.api.errors import register_error_handlers
from clipatlas.api.routes.rough_cut import router as rough_cut_router
from clipatlas.director.story_models import StoryEvidenceReference, StoryOutline, StoryOutlineNode
from clipatlas.director.story_service import StoryDirectorService
from clipatlas.director.story_store import StoryOutlineStore
from clipatlas.roughcut.errors import (
    RoughCutConfigurationError,
    RoughCutRetrievalError,
    RoughCutTimingError,
)
from clipatlas.roughcut.models import PlannerSettings, RoughCutPlan
from clipatlas.roughcut.store import RoughCutStore
from clipatlas.speech.models import NarrationSourceMode, NarrationTrack, TimingQuality


class StubPlanner:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[UUID, int, list[UUID] | None]] = []

    async def create_plan(
        self,
        project_id: UUID,
        *,
        top_k: int = 12,
        video_ids: list[UUID] | None = None,
    ) -> RoughCutPlan:
        self.calls.append((project_id, top_k, video_ids))
        if self.error is not None:
            raise self.error
        return RoughCutPlan(
            project_id=project_id,
            narration_track_id=uuid4(),
            narration_revision=1,
            revision=1,
            total_duration_ms=1000,
            settings=PlannerSettings(top_k=top_k),
            beats=[],
            clips=[],
        )


class StoryStubPlanner(StubPlanner):
    def __init__(self) -> None:
        super().__init__()
        self.story_calls: list[dict[str, object]] = []

    async def create_plan(
        self,
        project_id: UUID,
        *,
        top_k: int = 12,
        video_ids: list[UUID] | None = None,
        narration_track_id: UUID | None = None,
        story_outline: StoryOutline | None = None,
        story_node_narration_unit_ids: dict[UUID, list[UUID]] | None = None,
    ) -> RoughCutPlan:
        self.story_calls.append({
            "project_id": project_id,
            "top_k": top_k,
            "video_ids": video_ids,
            "narration_track_id": narration_track_id,
            "story_outline": story_outline,
            "story_node_narration_unit_ids": story_node_narration_unit_ids,
        })
        return await super().create_plan(project_id, top_k=top_k, video_ids=video_ids)


class OriginalAudioStub:
    def __init__(self, track: NarrationTrack, mapping: dict[UUID, list[UUID]]) -> None:
        self.track = track
        self.mapping = mapping
        self.calls: list[tuple[UUID, StoryOutline]] = []

    async def prepare(
        self,
        project_id: UUID,
        outline: StoryOutline,
    ) -> tuple[NarrationTrack, dict[UUID, list[UUID]]]:
        self.calls.append((project_id, outline))
        return self.track, self.mapping


class StoryTtsStub:
    def __init__(self, track: NarrationTrack, mapping: dict[UUID, list[UUID]]) -> None:
        self.track = track
        self.mapping = mapping
        self.calls: list[tuple[UUID, StoryOutline, UUID]] = []

    async def prepare(
        self,
        project_id: UUID,
        outline: StoryOutline,
        speech_profile_id: UUID,
    ) -> tuple[NarrationTrack, dict[UUID, list[UUID]]]:
        self.calls.append((project_id, outline, speech_profile_id))
        return self.track, self.mapping


def _app(
    tmp_path: Path,
    *,
    planner: StubPlanner | None,
) -> tuple[FastAPI, RoughCutStore]:
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(rough_cut_router)
    store = RoughCutStore(tmp_path / "roughcut.sqlite3")
    app.state.rough_cut_store = store
    app.state.rough_cut_planner = planner
    return app, store


def _story_service(tmp_path: Path, outline: StoryOutline) -> StoryDirectorService:
    store = StoryOutlineStore(tmp_path / "director.sqlite3")
    store.save(outline)
    return StoryDirectorService(evidence_builder=None, analyzer=None, store=store)  # type: ignore[arg-type]


def _outline(project_id: UUID, *, confirmed: bool) -> StoryOutline:
    node = StoryOutlineNode(
        order=0,
        title="Visual opening",
        summary="A real visual event",
        evidence=[StoryEvidenceReference(
            evidence_id="visual:opening",
            kind="visual",
            video_id=uuid4(),
            segment_id=uuid4(),
            start_ms=1_000,
            end_ms=4_000,
            text="A real visual event",
        )],
    )
    return StoryOutline(
        project_id=project_id,
        revision=1,
        skill_name="story.md",
        skill_hash="a" * 64,
        summary="Story",
        nodes=[node],
        status="confirmed" if confirmed else "draft",
    )


def test_create_plan_passes_project_top_k_and_video_filter(tmp_path: Path) -> None:
    planner = StubPlanner()
    app, _ = _app(tmp_path, planner=planner)
    client = TestClient(app)
    project_id = uuid4()
    video_ids = [uuid4(), uuid4()]

    response = client.post(
        "/api/v1/rough-cut/plans",
        json={
            "project_id": str(project_id),
            "top_k": 7,
            "video_ids": [str(item) for item in video_ids],
        },
    )

    assert response.status_code == 200
    assert planner.calls == [(project_id, 7, video_ids)]
    assert response.json()["project_id"] == str(project_id)
    assert response.json()["settings"]["top_k"] == 7


def test_create_plan_uses_default_top_k_12(tmp_path: Path) -> None:
    planner = StubPlanner()
    app, _ = _app(tmp_path, planner=planner)
    client = TestClient(app)
    project_id = uuid4()

    response = client.post(
        "/api/v1/rough-cut/plans",
        json={"project_id": str(project_id)},
    )

    assert response.status_code == 200
    assert planner.calls == [(project_id, 12, None)]


def test_create_plan_resolves_confirmed_story_outline_and_mapping(tmp_path: Path) -> None:
    project_id = uuid4()
    outline = _outline(project_id, confirmed=True)
    narration_track_id = uuid4()
    unit_id = uuid4()
    planner = StoryStubPlanner()
    app, _ = _app(tmp_path, planner=planner)
    app.state.story_director_service = _story_service(tmp_path, outline)

    response = TestClient(app).post(
        "/api/v1/rough-cut/plans",
        json={
            "project_id": str(project_id),
            "story_outline_id": str(outline.id),
            "narration_track_id": str(narration_track_id),
            "story_node_narration_unit_ids": {str(outline.nodes[0].id): [str(unit_id)]},
        },
    )

    assert response.status_code == 200
    assert planner.story_calls == [{
        "project_id": project_id,
        "top_k": 12,
        "video_ids": None,
        "narration_track_id": narration_track_id,
        "story_outline": outline,
        "story_node_narration_unit_ids": {outline.nodes[0].id: [unit_id]},
    }]


def test_create_plan_resolves_original_audio_before_existing_story_planner(
    tmp_path: Path,
) -> None:
    project_id = uuid4()
    outline = _outline(project_id, confirmed=True)
    unit_id = uuid4()
    track = NarrationTrack(
        project_id=project_id,
        source_mode=NarrationSourceMode.IMPORTED,
        script_hash="original-audio",
        duration_ms=3_000,
        timing_quality=TimingQuality.UNIT_EXACT,
    )
    original_audio = OriginalAudioStub(track, {outline.nodes[0].id: [unit_id]})
    planner = StoryStubPlanner()
    app, _ = _app(tmp_path, planner=planner)
    app.state.story_director_service = _story_service(tmp_path, outline)
    app.state.original_audio_narration = original_audio

    response = TestClient(app).post(
        "/api/v1/rough-cut/plans",
        json={
            "project_id": str(project_id),
            "story_outline_id": str(outline.id),
            "voice_strategy": "original_audio",
        },
    )

    assert response.status_code == 200
    assert original_audio.calls == [(project_id, outline)]
    assert planner.story_calls == [{
        "project_id": project_id,
        "top_k": 12,
        "video_ids": None,
        "narration_track_id": track.id,
        "story_outline": outline,
        "story_node_narration_unit_ids": {outline.nodes[0].id: [unit_id]},
    }]


def test_create_plan_resolves_story_tts_before_existing_story_planner(
    tmp_path: Path,
) -> None:
    project_id = uuid4()
    outline = _outline(project_id, confirmed=True)
    profile_id = uuid4()
    unit_id = uuid4()
    track = NarrationTrack(
        project_id=project_id,
        source_mode=NarrationSourceMode.TTS,
        script_hash="story-tts",
        speech_profile_id=profile_id,
        duration_ms=3_000,
        timing_quality=TimingQuality.UNIT_EXACT,
    )
    story_tts = StoryTtsStub(track, {outline.nodes[0].id: [unit_id]})
    planner = StoryStubPlanner()
    app, _ = _app(tmp_path, planner=planner)
    app.state.story_director_service = _story_service(tmp_path, outline)
    app.state.story_tts_narration = story_tts

    response = TestClient(app).post(
        "/api/v1/rough-cut/plans",
        json={
            "project_id": str(project_id),
            "story_outline_id": str(outline.id),
            "voice_strategy": "tts",
            "speech_profile_id": str(profile_id),
        },
    )

    assert response.status_code == 200
    assert story_tts.calls == [(project_id, outline, profile_id)]
    assert planner.story_calls == [{
        "project_id": project_id,
        "top_k": 12,
        "video_ids": None,
        "narration_track_id": track.id,
        "story_outline": outline,
        "story_node_narration_unit_ids": {outline.nodes[0].id: [unit_id]},
    }]


def test_traditional_rough_cut_does_not_use_original_audio_strategy(tmp_path: Path) -> None:
    project_id = uuid4()
    track = NarrationTrack(
        project_id=project_id,
        source_mode=NarrationSourceMode.IMPORTED,
        script_hash="unused",
        duration_ms=1_000,
        timing_quality=TimingQuality.UNIT_EXACT,
    )
    original_audio = OriginalAudioStub(track, {})
    planner = StubPlanner()
    app, _ = _app(tmp_path, planner=planner)
    app.state.original_audio_narration = original_audio

    response = TestClient(app).post(
        "/api/v1/rough-cut/plans",
        json={"project_id": str(project_id)},
    )

    assert response.status_code == 200
    assert original_audio.calls == []
    assert planner.calls == [(project_id, 12, None)]


def test_create_plan_rejects_draft_story_outline(tmp_path: Path) -> None:
    project_id = uuid4()
    outline = _outline(project_id, confirmed=False)
    planner = StoryStubPlanner()
    app, _ = _app(tmp_path, planner=planner)
    app.state.story_director_service = _story_service(tmp_path, outline)

    response = TestClient(app).post(
        "/api/v1/rough-cut/plans",
        json={
            "project_id": str(project_id),
            "story_outline_id": str(outline.id),
            "story_node_narration_unit_ids": {str(outline.nodes[0].id): []},
        },
    )

    assert response.status_code == 409
    assert planner.story_calls == []


def test_create_plan_rejects_story_outline_from_another_project(tmp_path: Path) -> None:
    owner_project_id = uuid4()
    request_project_id = uuid4()
    outline = _outline(owner_project_id, confirmed=True)
    planner = StoryStubPlanner()
    app, _ = _app(tmp_path, planner=planner)
    app.state.story_director_service = _story_service(tmp_path, outline)

    response = TestClient(app).post(
        "/api/v1/rough-cut/plans",
        json={
            "project_id": str(request_project_id),
            "story_outline_id": str(outline.id),
            "story_node_narration_unit_ids": {str(outline.nodes[0].id): []},
        },
    )

    assert response.status_code == 404
    assert planner.story_calls == []


@pytest.mark.parametrize("top_k", [0, 101])
def test_create_plan_validates_top_k_range(tmp_path: Path, top_k: int) -> None:
    planner = StubPlanner()
    app, _ = _app(tmp_path, planner=planner)
    client = TestClient(app)

    response = client.post(
        "/api/v1/rough-cut/plans",
        json={"project_id": str(uuid4()), "top_k": top_k},
    )

    assert response.status_code == 422
    assert planner.calls == []


def test_create_plan_returns_stable_unavailable_error_when_planner_missing(
    tmp_path: Path,
) -> None:
    app, _ = _app(tmp_path, planner=None)
    client = TestClient(app)

    response = client.post(
        "/api/v1/rough-cut/plans",
        json={"project_id": str(uuid4())},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "rough_cut_unavailable"


def test_missing_active_plan_returns_normalized_404(tmp_path: Path) -> None:
    app, _ = _app(tmp_path, planner=StubPlanner())
    client = TestClient(app)

    response = client.get(
        "/api/v1/rough-cut/plans/active",
        params={"project_id": str(uuid4())},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "rough_cut_plan_not_found"


def test_project_rough_cut_history_returns_revision_history(tmp_path: Path) -> None:
    planner = StubPlanner()
    app, store = _app(tmp_path, planner=planner)
    client = TestClient(app)
    project_id = uuid4()
    first = RoughCutPlan(
        project_id=project_id,
        narration_track_id=uuid4(),
        narration_revision=1,
        revision=1,
        total_duration_ms=1000,
        settings=PlannerSettings(),
        beats=[],
        clips=[],
    )
    second = RoughCutPlan(
        project_id=project_id,
        narration_track_id=uuid4(),
        narration_revision=2,
        revision=2,
        total_duration_ms=1200,
        settings=PlannerSettings(),
        beats=[],
        clips=[],
    )
    store.save_plan(first)
    store.save_plan(second)

    response = client.get(f"/api/v1/projects/{project_id}/rough-cut/plans")
    empty = client.get(f"/api/v1/projects/{uuid4()}/rough-cut/plans")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [str(second.id), str(first.id)]
    assert empty.status_code == 200
    assert empty.json() == []
    assert planner.calls == []


def test_get_plan_by_id_returns_persisted_plan(tmp_path: Path) -> None:
    app, store = _app(tmp_path, planner=StubPlanner())
    client = TestClient(app)
    project_id = uuid4()
    plan = RoughCutPlan(
        project_id=project_id,
        narration_track_id=uuid4(),
        narration_revision=1,
        revision=1,
        total_duration_ms=1000,
        settings=PlannerSettings(),
        beats=[],
        clips=[],
    )
    store.save_plan(plan)

    response = client.get(f"/api/v1/rough-cut/plans/{plan.id}")

    assert response.status_code == 200
    assert response.json()["id"] == str(plan.id)


def test_unknown_plan_id_returns_normalized_404(tmp_path: Path) -> None:
    app, _ = _app(tmp_path, planner=StubPlanner())
    client = TestClient(app)

    response = client.get(f"/api/v1/rough-cut/plans/{uuid4()}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "rough_cut_plan_not_found"


@pytest.mark.parametrize(
    "error",
    [
        RoughCutConfigurationError("active narration missing"),
        RoughCutTimingError("narration timing is not authoritative"),
    ],
)
def test_not_ready_planning_errors_map_to_409(tmp_path: Path, error: Exception) -> None:
    app, _ = _app(tmp_path, planner=StubPlanner(error=error))
    client = TestClient(app)

    response = client.post(
        "/api/v1/rough-cut/plans",
        json={"project_id": str(uuid4())},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "rough_cut_not_ready"


def test_retrieval_error_maps_to_503(tmp_path: Path) -> None:
    app, _ = _app(
        tmp_path,
        planner=StubPlanner(error=RoughCutRetrievalError("no footage candidates")),
    )
    client = TestClient(app)

    response = client.post(
        "/api/v1/rough-cut/plans",
        json={"project_id": str(uuid4())},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "rough_cut_retrieval_failed"

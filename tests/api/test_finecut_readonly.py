from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from clipatlas.api.routes.finecut import router as finecut_router
from clipatlas.library.models import LibraryItem, LibraryItemStatus
from clipatlas.roughcut.models import PlannerSettings, RoughCutClip, RoughCutPlan, ScriptBeat, CandidateScore
from clipatlas.speech.models import NarrationSourceMode, NarrationTrack, TimingQuality
from finecut.models import Clip, TimelineDocument, Track


class RoughCutStoreStub:
    def __init__(self, plan: RoughCutPlan) -> None:
        self.plan = plan

    def get_plan(self, plan_id: UUID) -> RoughCutPlan | None:
        return self.plan if plan_id == self.plan.id else None


class NarrationStoreStub:
    def __init__(self, track: NarrationTrack) -> None:
        self.track = track

    def get_track(self, track_id: UUID) -> NarrationTrack | None:
        return self.track if track_id == self.track.id else None


class FineCutTimelineStoreStub:
    def __init__(self) -> None:
        self.document: TimelineDocument | None = None

    def save(self, document: TimelineDocument) -> None:
        self.document = document.model_copy(deep=True)

    def get(self, project_id: UUID, source_plan_id: UUID) -> TimelineDocument | None:
        if self.document is None:
            return None
        if self.document.project_id != project_id or self.document.source_plan_id != source_plan_id:
            return None
        return self.document.model_copy(deep=True)


class LibraryStoreStub:
    def __init__(self, items: list[LibraryItem]) -> None:
        self.items = items

    def list_items(self, *, limit: int = 100, offset: int = 0, **_: object) -> list[LibraryItem]:
        return self.items[offset : offset + limit]


def make_client() -> tuple[TestClient, RoughCutPlan, ScriptBeat]:
    project_id = uuid4()
    track_id = uuid4()
    candidate_video_id = uuid4()
    beat = ScriptBeat(
        project_id=project_id,
        narration_track_id=track_id,
        sequence=0,
        text="当前句",
        timeline_start_ms=0,
        timeline_end_ms=2000,
        target_duration_ms=2000,
        query_text="当前句",
        retrieval_intent={
            "candidate_matrix": [
                {
                    "requirement_id": "req-1",
                    "sentence_id": "sentence-1",
                    "source_quote": "当前句",
                    "importance": "S",
                    "candidate_type": "window",
                    "candidate_id": str(uuid4()),
                    "video_id": str(candidate_video_id),
                    "start_ms": 1000,
                    "end_ms": 3000,
                    "match_level": "DIRECT",
                    "pollution_level": "clean",
                    "vector_score": 0.91,
                }
            ]
        },
    )
    plan = RoughCutPlan(
        project_id=project_id,
        narration_track_id=track_id,
        narration_revision=1,
        revision=1,
        total_duration_ms=2000,
        settings=PlannerSettings(),
        beats=[beat],
        clips=[],
    )
    track = NarrationTrack(
        id=track_id,
        project_id=project_id,
        source_mode=NarrationSourceMode.TTS,
        script_hash="hash",
        audio_uri="D:/audio/narration.wav",
        duration_ms=2000,
        timing_quality=TimingQuality.WORD_EXACT,
        revision=1,
    )
    item = LibraryItem(
        root_id=uuid4(),
        source_path="D:/media/candidate.mp4",
        size_bytes=1,
        mtime_ns=1,
        fingerprint="candidate",
        status=LibraryItemStatus.COMPLETED,
        video_id=candidate_video_id,
    )

    app = FastAPI()
    app.include_router(finecut_router)
    app.state.rough_cut_store = RoughCutStoreStub(plan)
    app.state.narration_store = NarrationStoreStub(track)
    app.state.finecut_timeline_store = FineCutTimelineStoreStub()
    app.state.library_store = LibraryStoreStub([item])
    return TestClient(app), plan, beat


def test_finecut_readonly_routes_project_existing_contracts() -> None:
    client, plan, beat = make_client()
    timeline = client.get(f"/api/v1/finecut/plans/{plan.id}/timeline")
    narration = client.get(f"/api/v1/finecut/plans/{plan.id}/narration")
    candidates = client.get(f"/api/v1/finecut/plans/{plan.id}/candidates/{beat.id}")
    assert timeline.status_code == 200
    assert timeline.json()["source_plan_id"] == str(plan.id)
    assert narration.status_code == 200
    assert narration.json()["segments"][0]["id"] == str(beat.id)
    assert candidates.status_code == 200
    assert candidates.json()["context_id"] == str(beat.id)
    assert candidates.json()["items"][0]["display_level"] == "S"


def test_finecut_readonly_routes_return_404_for_unknown_plan_or_context() -> None:
    client, plan, _ = make_client()
    assert client.get(f"/api/v1/finecut/plans/{uuid4()}/timeline").status_code == 404
    assert client.get(f"/api/v1/finecut/plans/{plan.id}/candidates/{uuid4()}").status_code == 404


def test_saved_finecut_timeline_wins_over_roughcut_regeneration() -> None:
    client, plan, _ = make_client()
    initial = client.get(f"/api/v1/finecut/plans/{plan.id}/timeline")
    assert initial.status_code == 200
    edited = initial.json()
    edited["width"] = 1280
    saved = client.put(f"/api/v1/finecut/plans/{plan.id}/timeline", json=edited)
    assert saved.status_code == 200
    reloaded = client.get(f"/api/v1/finecut/plans/{plan.id}/timeline")
    assert reloaded.status_code == 200
    assert reloaded.json()["width"] == 1280


def test_phase3b_trim_result_survives_save_and_reload() -> None:
    client, plan, _ = make_client()
    clip = Clip(
        source_id="source-a",
        source_path="D:/media/a.mp4",
        timeline_start_ms=0,
        duration_ms=1500,
        source_in_ms=100,
        source_out_ms=1600,
    )
    document = TimelineDocument(
        project_id=plan.project_id,
        source_plan_id=plan.id,
        width=1920,
        height=1080,
        fps=30,
        duration_ms=2000,
        tracks=[Track(kind="video", clips=[clip])],
    )
    trimmed = client.post(
        "/api/v1/finecut/edit/trim",
        json={
            "document": document.model_dump(mode="json"),
            "target_clip_id": str(clip.id),
            "edge": "right",
            "delta_ms": 500,
        },
    )
    assert trimmed.status_code == 200
    saved = client.put(f"/api/v1/finecut/plans/{plan.id}/timeline", json=trimmed.json())
    assert saved.status_code == 200
    reloaded = client.get(f"/api/v1/finecut/plans/{plan.id}/timeline")
    assert reloaded.status_code == 200
    result = reloaded.json()["tracks"][0]["clips"][0]
    assert result["duration_ms"] == 1000
    assert result["source_in_ms"] == 100
    assert result["source_out_ms"] == 1100


def test_finecut_media_reference_uses_existing_library_item() -> None:
    client, plan, beat = make_client()
    media_id = beat.retrieval_intent["candidate_matrix"][0]["video_id"]
    response = client.get(f"/api/v1/finecut/media/{media_id}")
    assert response.status_code == 200
    assert response.json() == {
        "media_id": media_id,
        "source_uri": "D:/media/candidate.mp4",
    }
    assert client.get(f"/api/v1/finecut/media/{uuid4()}").status_code == 404


def test_finecut_timeline_put_rejects_wrong_plan_identity() -> None:
    client, plan, _ = make_client()
    document = client.get(f"/api/v1/finecut/plans/{plan.id}/timeline").json()
    document["source_plan_id"] = str(uuid4())
    response = client.put(f"/api/v1/finecut/plans/{plan.id}/timeline", json=document)
    assert response.status_code == 400


def _score(segment_id: UUID) -> CandidateScore:
    return CandidateScore(
        segment_id=segment_id,
        semantic_score=1,
        action_score=1,
        scene_score=1,
        emotion_score=1,
        duration_fit_score=1,
        quality_score=1,
        continuity_bonus=0,
        reuse_penalty=0,
        total_score=1,
    )


def _rough_clip(beat: ScriptBeat, *, segment_id: UUID, video_id: UUID, source_uri: str) -> RoughCutClip:
    return RoughCutClip(
        beat_id=beat.id,
        segment_id=segment_id,
        video_id=video_id,
        source_uri=source_uri,
        source_in_ms=0,
        source_out_ms=2000,
        timeline_in_ms=0,
        timeline_out_ms=2000,
        score=1,
        score_breakdown=_score(segment_id),
        selection_reason="test",
    )


def _add_library_item(client: TestClient, *, video_id: UUID, path: str) -> None:
    store = client.app.state.library_store
    assert isinstance(store, LibraryStoreStub)
    store.items.append(LibraryItem(
        root_id=uuid4(), source_path=path, size_bytes=1, mtime_ns=1,
        fingerprint=str(video_id), status=LibraryItemStatus.COMPLETED, video_id=video_id,
    ))


def test_phase4b_resolver_r1_resolves_original_segment_source_to_plan_video() -> None:
    client, plan, beat = make_client()
    segment_id = uuid4()
    video_id = uuid4()
    plan.clips = [_rough_clip(beat, segment_id=segment_id, video_id=video_id, source_uri="D:/media/original.mp4")]
    _add_library_item(client, video_id=video_id, path="D:/media/original.mp4")

    response = client.get(f"/api/v1/finecut/plans/{plan.id}/media-resolution/{segment_id}")

    assert response.status_code == 200
    assert response.json() == {"media_id": str(video_id), "source_uri": "D:/media/original.mp4"}


def test_phase4b_resolver_r2_resolves_direct_media_source() -> None:
    client, plan, beat = make_client()
    media_id = UUID(str(beat.retrieval_intent["candidate_matrix"][0]["video_id"]))

    response = client.get(f"/api/v1/finecut/plans/{plan.id}/media-resolution/{media_id}")

    assert response.status_code == 200
    assert response.json()["media_id"] == str(media_id)


def test_phase4b_resolver_r3_returns_404_when_source_has_no_deterministic_route() -> None:
    client, plan, _ = make_client()

    response = client.get(f"/api/v1/finecut/plans/{plan.id}/media-resolution/{uuid4()}")

    assert response.status_code == 404


def test_phase4b_resolver_r4_returns_409_for_conflicting_segment_and_direct_media_routes() -> None:
    client, plan, beat = make_client()
    shared_id = UUID(str(beat.retrieval_intent["candidate_matrix"][0]["video_id"]))
    plan_video_id = uuid4()
    plan.clips = [_rough_clip(beat, segment_id=shared_id, video_id=plan_video_id, source_uri="D:/media/plan.mp4")]
    _add_library_item(client, video_id=plan_video_id, path="D:/media/plan.mp4")

    response = client.get(f"/api/v1/finecut/plans/{plan.id}/media-resolution/{shared_id}")

    assert response.status_code == 409


def test_phase4b_resolver_r5_accepts_same_video_from_both_deterministic_routes() -> None:
    client, plan, beat = make_client()
    shared_id = UUID(str(beat.retrieval_intent["candidate_matrix"][0]["video_id"]))
    plan.clips = [_rough_clip(beat, segment_id=shared_id, video_id=shared_id, source_uri="D:/media/candidate.mp4")]

    response = client.get(f"/api/v1/finecut/plans/{plan.id}/media-resolution/{shared_id}")

    assert response.status_code == 200
    assert response.json() == {"media_id": str(shared_id), "source_uri": "D:/media/candidate.mp4"}

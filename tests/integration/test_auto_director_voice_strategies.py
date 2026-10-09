from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from clipatlas.api.errors import register_error_handlers
from clipatlas.api.routes.rough_cut import router as rough_cut_router
from clipatlas.asr.models import ASRChunkRecord, ASRChunkStatus, ASRSentence
from clipatlas.asr.store import ASRStore
from clipatlas.catalog.store import CatalogStore
from clipatlas.director.story_models import (
    StoryEvidenceReference,
    StoryOutline,
    StoryOutlineNode,
)
from clipatlas.director.story_service import StoryDirectorService
from clipatlas.director.story_store import StoryOutlineStore
from clipatlas.domain.models import AnnotationOrigin, SemanticAnnotation, VideoAsset
from clipatlas.retrieval.search import SemanticSearchHit
from clipatlas.roughcut.planner import RoughCutPlanner
from clipatlas.roughcut.store import RoughCutStore
from clipatlas.speech.contracts import SpeechProviderCapabilities
from clipatlas.speech.models import (
    SpeechProfile,
    SpeechSynthesisRequest,
    SpeechSynthesisResult,
)
from clipatlas.speech.original_audio import OriginalAudioNarrationAdapter
from clipatlas.speech.service import NarrationService
from clipatlas.speech.store import NarrationStore
from clipatlas.speech.story_tts import StoryTtsNarrationAdapter
from clipatlas.video.models import IngestedVideo, MediaMetadata


class LocalAudio:
    def __init__(self) -> None:
        self.durations: dict[Path, int] = {}
        self.silence_calls: list[int] = []

    @staticmethod
    def _write(path: Path, data: bytes = b"audio") -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    async def normalize(
        self,
        source: Path,
        destination: Path,
        sample_rate: int = 48_000,
    ) -> Path:
        del sample_rate
        self._write(destination, source.read_bytes())
        self.durations[destination.resolve()] = 1_000
        return destination

    async def extract(
        self,
        source: Path,
        destination: Path,
        *,
        start_ms: int,
        end_ms: int,
        sample_rate: int = 48_000,
    ) -> Path:
        del sample_rate
        assert source.is_file()
        self._write(destination)
        self.durations[destination.resolve()] = end_ms - start_ms
        return destination

    async def silence(
        self,
        destination: Path,
        *,
        duration_ms: int,
        sample_rate: int = 48_000,
    ) -> Path:
        del sample_rate
        self.silence_calls.append(duration_ms)
        self._write(destination, b"silence")
        self.durations[destination.resolve()] = duration_ms
        return destination

    async def concat(self, inputs: list[Path], destination: Path) -> Path:
        self._write(destination, b"".join(path.read_bytes() for path in inputs))
        self.durations[destination.resolve()] = sum(
            self.durations[path.resolve()] for path in inputs
        )
        return destination

    async def probe_duration_ms(self, source: Path) -> int:
        return self.durations[source.resolve()]


class LocalSpeechProvider:
    name = "local"
    model = "local-tts"
    capabilities = SpeechProviderCapabilities()

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def list_voices(self) -> list[object]:
        return []

    async def synthesize(self, request: SpeechSynthesisRequest) -> SpeechSynthesisResult:
        self.calls.append(request.text)
        return SpeechSynthesisResult(
            provider=self.name,
            model=self.model,
            audio_bytes=request.text.encode(),
            output_format="wav",
            sample_rate=48_000,
        )


class LocalStorySearch:
    def __init__(self, video_id: UUID) -> None:
        self.video_id = video_id
        self.queries: list[str] = []
        self.parse_calls = 0
        self.hits = [self._hit(index) for index in range(6)]

    def _hit(self, index: int) -> SemanticSearchHit:
        segment_id = uuid4()
        annotation = SemanticAnnotation(
            segment_id=segment_id,
            origin=AnnotationOrigin.AI,
            description=f"project story material {index}",
            confidence=0.9,
        )
        return SemanticSearchHit(
            segment_id=segment_id,
            video_id=self.video_id,
            source_uri=f"file:///project-story-{index}.mp4",
            source_start_ms=index * 10_000,
            source_end_ms=index * 10_000 + 8_000,
            score=0.9 - index * 0.01,
            effective_description=annotation.description,
            annotation=annotation,
            embedding_provider="local",
            embedding_model="local",
            embedding_dimensions=3,
        )

    def project_video_ids(self, project_id: UUID) -> list[UUID]:
        del project_id
        return [self.video_id]

    async def search(
        self,
        query: str,
        limit: int = 10,
        video_ids: list[UUID] | None = None,
    ) -> list[SemanticSearchHit]:
        self.queries.append(query)
        allowed = set(video_ids or [self.video_id])
        return [hit for hit in self.hits if hit.video_id in allowed][:limit]

    def parse_video(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        self.parse_calls += 1
        raise AssertionError("story execution must reuse parsed project evidence")


def _save_project_video(
    catalog: CatalogStore,
    tmp_path: Path,
    project_id: UUID,
) -> VideoAsset:
    source = tmp_path / "project.mp4"
    source.write_bytes(b"video")
    video = VideoAsset(
        filename=source.name,
        source_uri=source.resolve().as_uri(),
        duration_ms=60_000,
        width=1920,
        height=1080,
        fps=25.0,
    )
    catalog.save_prepared_video(
        IngestedVideo(
            video=video,
            metadata=MediaMetadata(
                duration_ms=60_000,
                width=1920,
                height=1080,
                fps=25.0,
                video_codec="h264",
                has_audio=True,
            ),
            segments=[],
            frames_by_segment={},
        ),
        project_id=project_id,
    )
    return video


def _outline(project_id: UUID, video_id: UUID) -> StoryOutline:
    return StoryOutline(
        project_id=project_id,
        revision=1,
        skill_name="acceptance-story.md",
        skill_hash="e" * 64,
        summary="真实项目故事",
        status="confirmed",
        nodes=[
            StoryOutlineNode(
                order=0,
                title="真实口播",
                summary="医生确认现场情况。",
                estimated_duration_ms=2_500,
                evidence=[StoryEvidenceReference(
                    evidence_id=f"asr:{video_id}:12000:14500",
                    kind="asr",
                    video_id=video_id,
                    start_ms=12_000,
                    end_ms=14_500,
                    text="医生确认现场情况",
                )],
            ),
            StoryOutlineNode(
                order=1,
                title="安静的走廊",
                summary="主人抱着猫走过医院走廊。",
                estimated_duration_ms=3_000,
                evidence=[StoryEvidenceReference(
                    evidence_id=f"visual:{video_id}:20000:23000",
                    kind="visual",
                    video_id=video_id,
                    segment_id=uuid4(),
                    start_ms=20_000,
                    end_ms=23_000,
                    text="主人抱着猫走过医院走廊",
                )],
            ),
        ],
    )


def _app(
    tmp_path: Path,
    *,
    outline: StoryOutline,
    narration_store: NarrationStore,
    search: LocalStorySearch,
    audio: LocalAudio,
) -> tuple[FastAPI, RoughCutStore]:
    outline_store = StoryOutlineStore(tmp_path / "story.sqlite3")
    outline_store.save(outline)
    rough_cut_store = RoughCutStore(tmp_path / "roughcut.sqlite3")
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(rough_cut_router)
    app.state.story_director_service = StoryDirectorService(
        evidence_builder=None,
        analyzer=None,
        store=outline_store,
    )
    app.state.rough_cut_store = rough_cut_store
    app.state.rough_cut_planner = RoughCutPlanner(
        narration_store=narration_store,
        search=search,
        store=rough_cut_store,
        audio_normalizer=audio,
        story_audio_root=tmp_path / "story-audio",
    )
    return app, rough_cut_store


def test_confirmed_story_original_audio_reaches_existing_rough_cut_end_to_end(
    tmp_path: Path,
) -> None:
    project_id = uuid4()
    library_db = tmp_path / "library.sqlite3"
    catalog = CatalogStore(library_db)
    asr_store = ASRStore(library_db)
    video = _save_project_video(catalog, tmp_path, project_id)
    asr_store.save_asr_chunk(ASRChunkRecord(
        video_id=video.id,
        start_ms=0,
        end_ms=60_000,
        provider="existing-asr",
        model="existing-model",
        revision=1,
        status=ASRChunkStatus.COMPLETED,
        attempt_count=1,
        sentences=[ASRSentence(
            start_ms=12_000,
            end_ms=14_500,
            text="医生确认现场情况",
        )],
    ))
    outline = _outline(project_id, video.id)
    narration_store = NarrationStore(tmp_path / "narration.sqlite3")
    search = LocalStorySearch(video.id)
    audio = LocalAudio()
    app, rough_cut_store = _app(
        tmp_path,
        outline=outline,
        narration_store=narration_store,
        search=search,
        audio=audio,
    )
    app.state.original_audio_narration = OriginalAudioNarrationAdapter(
        narration_store=narration_store,
        catalog=catalog,
        asr_store=asr_store,
        audio_normalizer=audio,
        narration_root=tmp_path / "narration",
    )

    response = TestClient(app).post("/api/v1/rough-cut/plans", json={
        "project_id": str(project_id),
        "story_outline_id": str(outline.id),
        "voice_strategy": "original_audio",
    })

    assert response.status_code == 200, response.text
    plan = response.json()
    assert [beat["kind"] for beat in plan["beats"]] == ["narration", "visual_only"]
    assert plan["total_duration_ms"] == 5_500
    assert len(plan["story_provenance"]["executed_nodes"]) == 2
    assert rough_cut_store.get_active_plan(project_id).id == UUID(plan["id"])
    assert audio.silence_calls == [3_000]
    assert len(asr_store.list_asr_chunks(video.id)) == 1
    assert search.parse_calls == 0


def test_confirmed_story_tts_reaches_existing_rough_cut_end_to_end(
    tmp_path: Path,
) -> None:
    project_id = uuid4()
    catalog = CatalogStore(tmp_path / "library.sqlite3")
    video = _save_project_video(catalog, tmp_path, project_id)
    outline = _outline(project_id, video.id)
    narration_store = NarrationStore(tmp_path / "narration.sqlite3")
    profile = SpeechProfile(
        project_id=project_id,
        provider="local",
        model="local-tts",
        voice_id="local-voice",
        locked=True,
    )
    narration_store.save_profile(profile)
    search = LocalStorySearch(video.id)
    audio = LocalAudio()
    provider = LocalSpeechProvider()
    narration_service = NarrationService(
        store=narration_store,
        audio_normalizer=audio,
        narration_root=tmp_path / "narration",
        provider=provider,
    )
    app, rough_cut_store = _app(
        tmp_path,
        outline=outline,
        narration_store=narration_store,
        search=search,
        audio=audio,
    )
    app.state.story_tts_narration = StoryTtsNarrationAdapter(
        service=narration_service,
        store=narration_store,
    )

    response = TestClient(app).post("/api/v1/rough-cut/plans", json={
        "project_id": str(project_id),
        "story_outline_id": str(outline.id),
        "voice_strategy": "tts",
        "speech_profile_id": str(profile.id),
    })

    assert response.status_code == 200, response.text
    plan = response.json()
    assert [beat["kind"] for beat in plan["beats"]] == ["narration", "narration"]
    assert len(plan["story_provenance"]["executed_nodes"]) == 2
    assert provider.calls == [node.summary for node in outline.nodes]
    assert rough_cut_store.get_active_plan(project_id).id == UUID(plan["id"])
    assert search.parse_calls == 0

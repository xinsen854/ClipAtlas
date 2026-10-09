from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest

from clipatlas.asr.models import ASRChunkRecord, ASRChunkStatus, ASRSentence
from clipatlas.asr.store import ASRStore
from clipatlas.catalog.store import CatalogStore
from clipatlas.director.story_models import (
    StoryEvidenceReference,
    StoryOutline,
    StoryOutlineNode,
)
from clipatlas.domain.models import VideoAsset
from clipatlas.roughcut.errors import RoughCutConfigurationError
from clipatlas.speech.original_audio import OriginalAudioNarrationAdapter
from clipatlas.speech.store import NarrationStore
from clipatlas.video.models import IngestedVideo, MediaMetadata


class RecordingAudioNormalizer:
    def __init__(self) -> None:
        self.extract_calls: list[tuple[Path, Path, int, int]] = []

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
        self.extract_calls.append((source, destination, start_ms, end_ms))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"original-audio")
        return destination


def _save_video(
    catalog: CatalogStore,
    tmp_path: Path,
    project_id: UUID,
    name: str,
) -> VideoAsset:
    source = tmp_path / name
    source.write_bytes(b"video")
    video = VideoAsset(
        filename=name,
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


def _save_asr(
    store: ASRStore,
    video_id: UUID,
    *,
    start_ms: int,
    end_ms: int,
    text: str,
) -> None:
    store.save_asr_chunk(
        ASRChunkRecord(
            video_id=video_id,
            start_ms=0,
            end_ms=60_000,
            provider="existing-asr",
            model="existing-model",
            revision=1,
            status=ASRChunkStatus.COMPLETED,
            attempt_count=1,
            sentences=[ASRSentence(start_ms=start_ms, end_ms=end_ms, text=text)],
        )
    )


def _outline(
    project_id: UUID,
    *,
    asr_video_id: UUID,
    visual_video_id: UUID,
) -> StoryOutline:
    return StoryOutline(
        project_id=project_id,
        revision=2,
        skill_name="story.md",
        skill_hash="c" * 64,
        summary="Original audio story",
        status="confirmed",
        nodes=[
            StoryOutlineNode(
                order=0,
                title="Spoken opening",
                summary="Real speech",
                estimated_duration_ms=9_000,
                evidence=[StoryEvidenceReference(
                    evidence_id=f"asr:{asr_video_id}:12000:14500:1:0",
                    kind="asr",
                    video_id=asr_video_id,
                    start_ms=12_000,
                    end_ms=14_500,
                    text="真实原声",
                )],
            ),
            StoryOutlineNode(
                order=1,
                title="Visual bridge",
                summary="Only a visual fact",
                estimated_duration_ms=3_000,
                evidence=[StoryEvidenceReference(
                    evidence_id=f"visual:{visual_video_id}:bridge",
                    kind="visual",
                    video_id=visual_video_id,
                    segment_id=uuid4(),
                    start_ms=20_000,
                    end_ms=23_000,
                    text="Only a visual fact",
                )],
            ),
        ],
    )


@pytest.mark.asyncio
async def test_original_audio_maps_persisted_asr_and_preserves_visual_only_node(
    tmp_path: Path,
) -> None:
    library_db = tmp_path / "library.sqlite3"
    catalog = CatalogStore(library_db)
    asr_store = ASRStore(library_db)
    narration_store = NarrationStore(tmp_path / "narration.sqlite3")
    project_id = uuid4()
    spoken_video = _save_video(catalog, tmp_path, project_id, "spoken.mp4")
    visual_video = _save_video(catalog, tmp_path, project_id, "visual.mp4")
    _save_asr(
        asr_store,
        spoken_video.id,
        start_ms=12_000,
        end_ms=14_500,
        text="真实原声",
    )
    outline = _outline(
        project_id,
        asr_video_id=spoken_video.id,
        visual_video_id=visual_video.id,
    )
    audio = RecordingAudioNormalizer()
    adapter = OriginalAudioNarrationAdapter(
        narration_store=narration_store,
        catalog=catalog,
        asr_store=asr_store,
        audio_normalizer=audio,
        narration_root=tmp_path / "narration",
    )

    track, mapping = await adapter.prepare(project_id, outline)

    units = narration_store.list_units(track.id)
    assert track.source_mode == "imported"
    assert track.duration_ms == 2_500
    assert [(unit.text, unit.start_ms, unit.end_ms) for unit in units] == [
        ("真实原声", 0, 2_500),
    ]
    assert mapping == {
        outline.nodes[0].id: [units[0].id],
        outline.nodes[1].id: [],
    }
    assert all(unit.text for unit in units)
    assert audio.extract_calls == [(
        tmp_path / "spoken.mp4",
        Path(units[0].audio_uri.removeprefix("file:///")),
        12_000,
        14_500,
    )]
    assert len(asr_store.list_asr_chunks(spoken_video.id)) == 1


@pytest.mark.asyncio
async def test_original_audio_rejects_asr_media_from_another_project(
    tmp_path: Path,
) -> None:
    library_db = tmp_path / "library.sqlite3"
    catalog = CatalogStore(library_db)
    asr_store = ASRStore(library_db)
    narration_store = NarrationStore(tmp_path / "narration.sqlite3")
    project_id = uuid4()
    other_project_id = uuid4()
    foreign_video = _save_video(catalog, tmp_path, other_project_id, "foreign.mp4")
    local_visual = _save_video(catalog, tmp_path, project_id, "visual.mp4")
    _save_asr(
        asr_store,
        foreign_video.id,
        start_ms=12_000,
        end_ms=14_500,
        text="真实原声",
    )
    outline = _outline(
        project_id,
        asr_video_id=foreign_video.id,
        visual_video_id=local_visual.id,
    )
    audio = RecordingAudioNormalizer()
    adapter = OriginalAudioNarrationAdapter(
        narration_store=narration_store,
        catalog=catalog,
        asr_store=asr_store,
        audio_normalizer=audio,
        narration_root=tmp_path / "narration",
    )

    with pytest.raises(RoughCutConfigurationError, match="current project"):
        await adapter.prepare(project_id, outline)

    assert narration_store.list_tracks(project_id) == []
    assert audio.extract_calls == []

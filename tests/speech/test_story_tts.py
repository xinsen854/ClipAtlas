from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from clipatlas.director.story_models import (
    StoryEvidenceReference,
    StoryOutline,
    StoryOutlineNode,
)
from clipatlas.speech.errors import SpeechConfigurationError
from clipatlas.speech.models import (
    NarrationSourceMode,
    NarrationTrack,
    NarrationUnit,
    SpeechProfile,
    TimingQuality,
)
from clipatlas.speech.service import split_narration_units
from clipatlas.speech.store import NarrationStore
from clipatlas.speech.story_tts import StoryTtsNarrationAdapter


class RecordingNarrationService:
    def __init__(self, store: NarrationStore) -> None:
        self._store = store
        self.calls: list[tuple[UUID, str, SpeechProfile]] = []

    async def create_tts_track(
        self,
        project_id: UUID,
        script: str,
        profile: SpeechProfile,
    ) -> NarrationTrack:
        self.calls.append((project_id, script, profile))
        texts = split_narration_units(script)
        track = NarrationTrack(
            project_id=project_id,
            source_mode=NarrationSourceMode.TTS,
            script_hash=sha256(script.encode()).hexdigest(),
            script=script,
            speech_profile_id=profile.id,
            duration_ms=len(texts) * 1_000,
            timing_quality=TimingQuality.UNIT_EXACT,
        )
        self._store.save_track(track)
        for sequence, text in enumerate(texts):
            self._store.save_unit(NarrationUnit(
                track_id=track.id,
                sequence=sequence,
                text=text,
                text_hash=sha256(text.encode()).hexdigest(),
                start_ms=sequence * 1_000,
                end_ms=(sequence + 1) * 1_000,
                source=NarrationSourceMode.TTS,
            ))
        return track


def _outline(project_id: UUID) -> StoryOutline:
    return StoryOutline(
        project_id=project_id,
        revision=2,
        skill_name="story.md",
        skill_hash="d" * 64,
        summary="Confirmed story",
        status="confirmed",
        nodes=[
            StoryOutlineNode(
                order=0,
                title="Opening",
                summary="第一句。第二句。",
                evidence=[StoryEvidenceReference(
                    evidence_id="asr:opening",
                    kind="asr",
                    video_id=uuid4(),
                    start_ms=1_000,
                    end_ms=3_000,
                    text="真实原声证据",
                )],
            ),
            StoryOutlineNode(
                order=1,
                title="Visual bridge",
                summary="视觉事实。",
                evidence=[StoryEvidenceReference(
                    evidence_id="visual:bridge",
                    kind="visual",
                    video_id=uuid4(),
                    segment_id=uuid4(),
                    start_ms=3_000,
                    end_ms=6_000,
                    text="真实视觉证据",
                )],
            ),
        ],
    )


@pytest.mark.asyncio
async def test_story_tts_reuses_narration_service_and_maps_every_confirmed_node(
    tmp_path: Path,
) -> None:
    project_id = uuid4()
    outline = _outline(project_id)
    store = NarrationStore(tmp_path / "narration.sqlite3")
    profile = SpeechProfile(
        project_id=project_id,
        provider="existing",
        model="existing-tts",
        voice_id="voice-1",
        locked=True,
    )
    store.save_profile(profile)
    service = RecordingNarrationService(store)
    adapter = StoryTtsNarrationAdapter(service=service, store=store)

    track, mapping = await adapter.prepare(project_id, outline, profile.id)

    units = store.list_units(track.id)
    assert service.calls == [(project_id, "第一句。第二句。\n视觉事实。", profile)]
    assert track.source_mode == "tts"
    assert mapping == {
        outline.nodes[0].id: [units[0].id, units[1].id],
        outline.nodes[1].id: [units[2].id],
    }
    assert [unit.text for unit in units] == ["第一句。", "第二句。", "视觉事实。"]


@pytest.mark.asyncio
async def test_story_tts_rejects_speech_profile_from_another_project(
    tmp_path: Path,
) -> None:
    project_id = uuid4()
    store = NarrationStore(tmp_path / "narration.sqlite3")
    profile = SpeechProfile(
        project_id=uuid4(),
        provider="existing",
        model="existing-tts",
        voice_id="voice-1",
        locked=True,
    )
    store.save_profile(profile)
    service = RecordingNarrationService(store)
    adapter = StoryTtsNarrationAdapter(service=service, store=store)

    with pytest.raises(SpeechConfigurationError, match="different project"):
        await adapter.prepare(project_id, _outline(project_id), profile.id)

    assert service.calls == []

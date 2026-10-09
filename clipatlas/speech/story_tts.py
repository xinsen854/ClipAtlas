from __future__ import annotations

from uuid import UUID

from clipatlas.director.story_models import StoryOutline
from clipatlas.roughcut.errors import RoughCutConfigurationError
from clipatlas.speech.errors import (
    SpeechAudioValidationError,
    SpeechConfigurationError,
    SpeechProfileNotFoundError,
)
from clipatlas.speech.models import NarrationTrack
from clipatlas.speech.service import NarrationService, split_narration_units
from clipatlas.speech.store import NarrationStore


class StoryTtsNarrationAdapter:
    """Map a confirmed Story outline onto the existing TTS narration runtime."""

    def __init__(self, *, service: NarrationService, store: NarrationStore) -> None:
        self._service = service
        self._store = store

    async def prepare(
        self,
        project_id: UUID,
        outline: StoryOutline,
        speech_profile_id: UUID,
    ) -> tuple[NarrationTrack, dict[UUID, list[UUID]]]:
        if outline.project_id != project_id or outline.status != "confirmed":
            raise RoughCutConfigurationError(
                "Story TTS requires the confirmed Story outline for this project"
            )
        profile = self._store.get_profile(speech_profile_id)
        if profile is None:
            raise SpeechProfileNotFoundError("speech profile not found")
        if profile.project_id != project_id:
            raise SpeechConfigurationError("Speech profile belongs to a different project")

        nodes = sorted(outline.nodes, key=lambda item: item.order)
        script = "\n".join(node.summary.strip() for node in nodes)
        track = await self._service.create_tts_track(project_id, script, profile)
        units = self._store.list_units(track.id)

        mapping: dict[UUID, list[UUID]] = {}
        cursor = 0
        for node in nodes:
            count = len(split_narration_units(node.summary))
            mapping[node.id] = [unit.id for unit in units[cursor:cursor + count]]
            cursor += count
        if cursor != len(units):
            raise SpeechAudioValidationError(
                "Story TTS units do not match the confirmed outline"
            )
        return track, mapping

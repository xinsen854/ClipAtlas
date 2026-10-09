from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from urllib.parse import unquote, urlparse
from uuid import UUID

from clipatlas.asr.models import ASRChunkStatus, ASRSentence
from clipatlas.asr.store import ASRStore
from clipatlas.catalog.store import CatalogStore
from clipatlas.director.story_models import StoryEvidenceReference, StoryOutline
from clipatlas.roughcut.errors import RoughCutConfigurationError
from clipatlas.speech.audio import AudioNormalizer
from clipatlas.speech.models import (
    NarrationSourceMode,
    NarrationTrack,
    NarrationUnit,
    TimingQuality,
)
from clipatlas.speech.store import NarrationStore


def _clean_text(value: str) -> str:
    return " ".join(value.split())[:1_200]


def _local_media_path(uri: str) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme not in {"", "file"}:
        raise RoughCutConfigurationError("Original audio requires local project media")
    if not parsed.scheme:
        return Path(uri)
    raw_path = unquote(parsed.path)
    if parsed.netloc:
        raw_path = f"//{parsed.netloc}{raw_path}"
    if len(raw_path) >= 3 and raw_path[0] == "/" and raw_path[2] == ":":
        raw_path = raw_path[1:]
    return Path(raw_path)


class OriginalAudioNarrationAdapter:
    """Prepare existing narration objects from persisted project ASR and media."""

    def __init__(
        self,
        *,
        narration_store: NarrationStore,
        catalog: CatalogStore,
        asr_store: ASRStore,
        audio_normalizer: AudioNormalizer,
        narration_root: Path,
    ) -> None:
        self._narration_store = narration_store
        self._catalog = catalog
        self._asr_store = asr_store
        self._audio = audio_normalizer
        self._root = narration_root.resolve()

    def _resolve_sentence(self, evidence: StoryEvidenceReference) -> ASRSentence:
        matches: list[tuple[int, ASRSentence]] = []
        expected_text = _clean_text(evidence.text)
        for record in self._asr_store.list_asr_chunks(evidence.video_id):
            if record.status != ASRChunkStatus.COMPLETED:
                continue
            for sentence in record.sentences:
                if (
                    sentence.start_ms == evidence.start_ms
                    and sentence.end_ms == evidence.end_ms
                    and _clean_text(sentence.text) == expected_text
                ):
                    matches.append((record.revision, sentence))
        if not matches:
            raise RoughCutConfigurationError(
                "Story ASR evidence is not available in the current project analysis"
            )
        return max(matches, key=lambda item: item[0])[1]

    async def prepare(
        self,
        project_id: UUID,
        outline: StoryOutline,
    ) -> tuple[NarrationTrack, dict[UUID, list[UUID]]]:
        if outline.project_id != project_id or outline.status != "confirmed":
            raise RoughCutConfigurationError(
                "Original audio requires the confirmed Story outline for this project"
            )

        project_video_ids = set(self._catalog.list_video_ids_for_project(project_id))
        prepared: dict[UUID, list[tuple[Path, ASRSentence]]] = {}
        ordered_nodes = sorted(outline.nodes, key=lambda item: item.order)
        for node in ordered_nodes:
            node_audio: list[tuple[Path, ASRSentence]] = []
            for evidence in node.evidence:
                if evidence.kind != "asr":
                    continue
                if evidence.video_id not in project_video_ids:
                    raise RoughCutConfigurationError(
                        "Story ASR media does not belong to the current project"
                    )
                video = self._catalog.get_video(evidence.video_id)
                if video is None or not video.source_uri.strip():
                    raise RoughCutConfigurationError("Story ASR source media is unavailable")
                node_audio.append((
                    _local_media_path(video.source_uri),
                    self._resolve_sentence(evidence),
                ))
            prepared[node.id] = node_audio

        script_parts = [
            _clean_text(sentence.text)
            for node in ordered_nodes
            for _, sentence in prepared[node.id]
        ]
        script = "\n".join(script_parts)
        source_duration_ms = sum(
            sentence.end_ms - sentence.start_ms
            for node in ordered_nodes
            for _, sentence in prepared[node.id]
        )
        track = NarrationTrack(
            project_id=project_id,
            source_mode=NarrationSourceMode.IMPORTED,
            script_hash=sha256(script.encode("utf-8")).hexdigest(),
            script=script or None,
            duration_ms=source_duration_ms,
            timing_quality=TimingQuality.UNIT_EXACT,
            revision=self._narration_store.next_track_revision(project_id),
        )

        mapping: dict[UUID, list[UUID]] = {}
        units: list[NarrationUnit] = []
        for node in ordered_nodes:
            mapping[node.id] = []
            for source_path, sentence in prepared[node.id]:
                sequence = len(units)
                unit_path = (
                    self._root / str(project_id) / str(track.id)
                    / "units" / f"{sequence:04d}.wav"
                )
                await self._audio.extract(
                    source_path,
                    unit_path,
                    start_ms=sentence.start_ms,
                    end_ms=sentence.end_ms,
                )
                text = _clean_text(sentence.text)
                unit = NarrationUnit(
                    track_id=track.id,
                    sequence=sequence,
                    text=text,
                    text_hash=sha256(text.encode("utf-8")).hexdigest(),
                    start_ms=0,
                    end_ms=sentence.end_ms - sentence.start_ms,
                    source=NarrationSourceMode.IMPORTED,
                    audio_uri=unit_path.resolve().as_uri(),
                )
                units.append(unit)
                mapping[node.id].append(unit.id)

        self._narration_store.save_track(track)
        for unit in units:
            self._narration_store.save_unit(unit)
        return track, mapping

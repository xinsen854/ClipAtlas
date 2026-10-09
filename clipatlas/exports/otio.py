from pathlib import Path
from uuid import UUID

import opentimelineio as otio  # type: ignore[import-untyped]

from clipatlas.exports.errors import (
    ExportInvariantError,
    ExportNotReadyError,
    OtioSerializationError,
)
from clipatlas.exports.models import OtioExportArtifact
from clipatlas.roughcut.models import RoughCutClip, RoughCutPlan
from clipatlas.speech.models import NarrationTrack

_TIME_RATE = 1000


def _rt(milliseconds: int) -> otio.opentime.RationalTime:
    return otio.opentime.RationalTime(milliseconds, _TIME_RATE)


def _time_range(start_ms: int, duration_ms: int) -> otio.opentime.TimeRange:
    return otio.opentime.TimeRange(start_time=_rt(start_ms), duration=_rt(duration_ms))


def _metadata_int(metadata: dict[str, object], key: str) -> int:
    value = metadata.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise OtioSerializationError(f"OTIO read-back metadata {key} is not an integer")
    return value


class OtioTimelineBuilder:
    """Build and serialize native OTIO timelines from canonical ClipAtlas decisions."""

    def build(
        self,
        plan: RoughCutPlan,
        narration: NarrationTrack,
    ) -> otio.schema.Timeline:
        clips = sorted(
            plan.clips,
            key=lambda clip: (clip.timeline_in_ms, clip.timeline_out_ms, str(clip.segment_id)),
        )
        self._validate(plan, narration, clips)

        timeline = otio.schema.Timeline(name=f"ClipAtlas Rough Cut r{plan.revision}")
        timeline.metadata["clipatlas"] = {
            "plan_id": str(plan.id),
            "project_id": str(plan.project_id),
            "narration_track_id": str(plan.narration_track_id),
            "narration_revision": plan.narration_revision,
            "rough_cut_revision": plan.revision,
            "total_duration_ms": plan.total_duration_ms,
            "timing_rate": _TIME_RATE,
            "subtitles": [
                {"text": subtitle.text, "start_ms": subtitle.start_ms, "end_ms": subtitle.end_ms}
                for subtitle in plan.subtitles
            ],
        }

        video_track = otio.schema.Track(name="Video", kind=otio.schema.TrackKind.Video)
        for rough_clip in clips:
            video_track.append(self._video_clip(rough_clip))

        audio_track = otio.schema.Track(name="Narration", kind=otio.schema.TrackKind.Audio)
        audio_track.append(self._narration_clip(narration))

        timeline.tracks.append(video_track)
        timeline.tracks.append(audio_track)
        return timeline

    def write_verified(
        self,
        timeline: otio.schema.Timeline,
        output_path: Path,
        *,
        plan_id: UUID,
        project_id: UUID,
        narration_track_id: UUID,
    ) -> OtioExportArtifact:
        resolved_path = output_path.expanduser().resolve()
        resolved_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            otio.adapters.write_to_file(timeline, str(resolved_path))
        except Exception as exc:
            resolved_path.unlink(missing_ok=True)
            raise OtioSerializationError(f"failed to write OTIO timeline: {exc}") from exc

        try:
            roundtrip = otio.adapters.read_from_file(str(resolved_path))
            metadata = roundtrip.metadata["clipatlas"]
            self._verify_roundtrip(
                roundtrip,
                metadata,
                plan_id=plan_id,
                project_id=project_id,
                narration_track_id=narration_track_id,
            )
        except Exception as exc:
            resolved_path.unlink(missing_ok=True)
            if isinstance(exc, OtioSerializationError):
                raise
            raise OtioSerializationError(f"failed to verify OTIO timeline: {exc}") from exc

        return OtioExportArtifact(
            plan_id=plan_id,
            project_id=project_id,
            narration_track_id=narration_track_id,
            output_path=resolved_path,
            total_duration_ms=_metadata_int(metadata, "total_duration_ms"),
            timing_rate=_metadata_int(metadata, "timing_rate"),
            rough_cut_revision=_metadata_int(metadata, "rough_cut_revision"),
            narration_revision=_metadata_int(metadata, "narration_revision"),
        )

    def _verify_roundtrip(
        self,
        timeline: otio.schema.Timeline,
        metadata: dict[str, object],
        *,
        plan_id: UUID,
        project_id: UUID,
        narration_track_id: UUID,
    ) -> None:
        expected_ids = {
            "plan_id": str(plan_id),
            "project_id": str(project_id),
            "narration_track_id": str(narration_track_id),
        }
        for key, expected in expected_ids.items():
            if metadata.get(key) != expected:
                raise OtioSerializationError(f"OTIO read-back verification failed for {key}")

        total_duration_ms = _metadata_int(metadata, "total_duration_ms")
        timing_rate = _metadata_int(metadata, "timing_rate")
        rough_cut_revision = _metadata_int(metadata, "rough_cut_revision")
        narration_revision = _metadata_int(metadata, "narration_revision")

        duration = timeline.duration()
        if timing_rate != _TIME_RATE or duration.rate != _TIME_RATE:
            raise OtioSerializationError("OTIO read-back verification failed for timing rate")
        if duration.value != total_duration_ms:
            raise OtioSerializationError("OTIO read-back verification failed for total duration")
        if rough_cut_revision < 1 or narration_revision < 1:
            raise OtioSerializationError("OTIO read-back revision metadata is invalid")
        if len(timeline.video_tracks()) != 1 or len(timeline.audio_tracks()) != 1:
            raise OtioSerializationError("OTIO read-back track structure is invalid")
        narration_clip = timeline.audio_tracks()[0][0]
        if narration_clip.source_range.duration.value != total_duration_ms:
            raise OtioSerializationError("OTIO narration duration changed during serialization")

    def _validate(
        self,
        plan: RoughCutPlan,
        narration: NarrationTrack,
        clips: list[RoughCutClip],
    ) -> None:
        if not clips:
            raise ExportInvariantError("rough cut plan must contain at least one clip")
        if clips[0].timeline_in_ms != 0:
            raise ExportInvariantError("rough cut timeline must start at 0 ms")

        previous_out = 0
        for clip in clips:
            if clip.timeline_in_ms != previous_out:
                raise ExportInvariantError("rough cut destination clips must be contiguous")
            if not clip.source_uri.strip():
                raise ExportInvariantError("rough cut clip source URI must not be empty")
            source_duration = clip.source_out_ms - clip.source_in_ms
            timeline_duration = clip.timeline_out_ms - clip.timeline_in_ms
            if source_duration != timeline_duration:
                raise ExportInvariantError("source and timeline durations must match")
            previous_out = clip.timeline_out_ms

        if previous_out != plan.total_duration_ms:
            raise ExportInvariantError("rough cut timeline must end at plan total duration")

        if narration.project_id != plan.project_id:
            raise ExportNotReadyError("narration project does not match rough cut project")
        if narration.id != plan.narration_track_id:
            raise ExportNotReadyError("narration track does not match rough cut plan")
        if narration.audio_uri is None or not narration.audio_uri.strip():
            raise ExportNotReadyError("narration audio is not ready for export")
        if narration.duration_ms != plan.total_duration_ms:
            raise ExportNotReadyError("narration duration does not match rough cut duration")

    def _video_clip(self, rough_clip: RoughCutClip) -> otio.schema.Clip:
        duration_ms = rough_clip.source_out_ms - rough_clip.source_in_ms
        source_range = _time_range(rough_clip.source_in_ms, duration_ms)
        media_reference = otio.schema.ExternalReference(
            target_url=rough_clip.source_uri,
            available_range=source_range,
        )
        clip = otio.schema.Clip(
            name=f"segment-{rough_clip.segment_id}",
            media_reference=media_reference,
            source_range=source_range,
        )
        clip.metadata["clipatlas"] = {
            "beat_id": str(rough_clip.beat_id),
            "segment_id": str(rough_clip.segment_id),
            "video_id": str(rough_clip.video_id),
            "source_in_ms": rough_clip.source_in_ms,
            "source_out_ms": rough_clip.source_out_ms,
            "timeline_in_ms": rough_clip.timeline_in_ms,
            "timeline_out_ms": rough_clip.timeline_out_ms,
            "score": rough_clip.score,
            "score_breakdown": rough_clip.score_breakdown.model_dump(mode="json"),
            "selection_reason": rough_clip.selection_reason,
        }
        return clip

    def _narration_clip(self, narration: NarrationTrack) -> otio.schema.Clip:
        assert narration.audio_uri is not None
        source_range = _time_range(0, narration.duration_ms)
        media_reference = otio.schema.ExternalReference(
            target_url=narration.audio_uri,
            available_range=source_range,
        )
        clip = otio.schema.Clip(
            name="Narration",
            media_reference=media_reference,
            source_range=source_range,
        )
        clip.metadata["clipatlas"] = {
            "narration_track_id": str(narration.id),
            "revision": narration.revision,
            "source_mode": narration.source_mode.value,
            "timing_quality": narration.timing_quality.value,
        }
        return clip

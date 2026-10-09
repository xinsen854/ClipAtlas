from pathlib import Path
from uuid import UUID

import opentimelineio as otio  # type: ignore[import-untyped]

from clipatlas.exports.errors import ExportInvariantError, ExportNotReadyError, OtioSerializationError
from clipatlas.exports.models import OtioExportArtifact
from clipatlas.roughcut.models import RoughCutPlan
from clipatlas.speech.models import NarrationTrack
from finecut.models import Clip, TimelineDocument, Track

_TIME_RATE = 1000
_FINECUT_METADATA_VERSION = 1


def _rt(milliseconds: int) -> otio.opentime.RationalTime:
    return otio.opentime.RationalTime(milliseconds, _TIME_RATE)


def _range(start_ms: int, duration_ms: int) -> otio.opentime.TimeRange:
    return otio.opentime.TimeRange(_rt(start_ms), _rt(duration_ms))


def _mapping(value: object) -> dict[str, object]:
    try:
        return dict(value) if value is not None else {}
    except (TypeError, ValueError):
        return {}


def _metadata_int(metadata: dict[str, object], key: str) -> int:
    value = metadata.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise OtioSerializationError(f"FineCut OTIO metadata {key} is not an integer")
    return value


class FineCutOtioBuilder:
    """Project the saved canonical FineCut document into portable OTIO.

    OTIO carries only the metadata that OTIO cannot represent natively. The
    TimelineDocument remains the canonical edit state; this builder creates no
    second store or editing model.
    """

    def build(
        self,
        document: TimelineDocument,
        plan: RoughCutPlan,
        narration: NarrationTrack,
    ) -> otio.schema.Timeline:
        video_track = self._video_track(document)
        self._validate_identity(document, plan, narration)

        total_duration_ms = max(document.duration_ms, narration.duration_ms)
        timeline = otio.schema.Timeline(name=f"ClipAtlas FineCut {plan.id}")
        timeline.metadata["clipatlas"] = {
            "plan_id": str(plan.id),
            "project_id": str(plan.project_id),
            "narration_track_id": str(narration.id),
            "narration_revision": narration.revision,
            "rough_cut_revision": plan.revision,
            "total_duration_ms": total_duration_ms,
            "timing_rate": _TIME_RATE,
            "subtitles": [
                {"text": item.text, "start_ms": item.start_ms, "end_ms": item.end_ms}
                for item in plan.subtitles
            ],
            "finecut": {
                "version": _FINECUT_METADATA_VERSION,
                "document_version": document.version,
                "width": document.width,
                "height": document.height,
                "fps": document.fps,
                "duration_ms": document.duration_ms,
                "video_track_id": str(video_track.id),
            },
        }

        otio_video = otio.schema.Track(name="Video", kind=otio.schema.TrackKind.Video)
        cursor_ms = 0
        for clip in sorted(video_track.clips, key=lambda item: (item.timeline_start_ms, str(item.id))):
            if clip.timeline_start_ms < cursor_ms:
                raise ExportInvariantError("FineCut video clips must not overlap for OTIO export")
            if clip.timeline_start_ms > cursor_ms:
                otio_video.append(
                    otio.schema.Gap(source_range=_range(0, clip.timeline_start_ms - cursor_ms))
                )
            otio_video.append(self._video_clip(clip))
            cursor_ms = clip.timeline_start_ms + clip.duration_ms
        if cursor_ms < document.duration_ms:
            otio_video.append(otio.schema.Gap(source_range=_range(0, document.duration_ms - cursor_ms)))

        otio_audio = otio.schema.Track(name="Narration", kind=otio.schema.TrackKind.Audio)
        otio_audio.append(self._narration_clip(narration))
        timeline.tracks.extend([otio_video, otio_audio])
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
        resolved = output_path.expanduser().resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        try:
            otio.adapters.write_to_file(timeline, str(resolved))
            roundtrip = otio.adapters.read_from_file(str(resolved))
            metadata = _mapping(roundtrip.metadata.get("clipatlas"))
            self._verify_roundtrip(
                roundtrip,
                metadata,
                plan_id=plan_id,
                project_id=project_id,
                narration_track_id=narration_track_id,
            )
        except Exception as exc:
            resolved.unlink(missing_ok=True)
            if isinstance(exc, OtioSerializationError):
                raise
            raise OtioSerializationError(f"failed to serialize FineCut OTIO: {exc}") from exc

        return OtioExportArtifact(
            plan_id=plan_id,
            project_id=project_id,
            narration_track_id=narration_track_id,
            output_path=resolved,
            total_duration_ms=_metadata_int(metadata, "total_duration_ms"),
            timing_rate=_metadata_int(metadata, "timing_rate"),
            rough_cut_revision=_metadata_int(metadata, "rough_cut_revision"),
            narration_revision=_metadata_int(metadata, "narration_revision"),
        )

    def _video_track(self, document: TimelineDocument) -> Track:
        video_tracks = [track for track in document.tracks if track.kind == "video"]
        if len(video_tracks) != 1:
            raise ExportInvariantError("FineCut OTIO export requires exactly one video track")
        if any(track.clips for track in document.tracks if track.kind != "video"):
            raise ExportInvariantError(
                "FineCut OTIO export cannot silently discard populated non-video tracks"
            )
        if not video_tracks[0].clips:
            raise ExportInvariantError("FineCut video track must contain at least one clip")
        return video_tracks[0]

    def _validate_identity(
        self,
        document: TimelineDocument,
        plan: RoughCutPlan,
        narration: NarrationTrack,
    ) -> None:
        if document.project_id != plan.project_id or document.source_plan_id != plan.id:
            raise ExportInvariantError("FineCut document identity does not match source plan")
        if narration.project_id != plan.project_id or narration.id != plan.narration_track_id:
            raise ExportNotReadyError("narration does not match FineCut source plan")
        if narration.audio_uri is None or not narration.audio_uri.strip():
            raise ExportNotReadyError("narration audio is not ready for export")

    def _video_clip(self, clip: Clip) -> otio.schema.Clip:
        source_range = _range(clip.source_in_ms, clip.duration_ms)
        item = otio.schema.Clip(
            name=f"finecut-{clip.id}",
            media_reference=otio.schema.ExternalReference(
                target_url=clip.source_path,
                available_range=source_range,
            ),
            source_range=source_range,
        )
        item.metadata["clipatlas"] = {
            "finecut": {
                "version": _FINECUT_METADATA_VERSION,
                "clip_id": str(clip.id),
                "source_id": clip.source_id,
                "opacity": clip.opacity,
                "volume": clip.volume,
                "transform": clip.transform,
                "effects": clip.effects,
            }
        }
        return item

    def _narration_clip(self, narration: NarrationTrack) -> otio.schema.Clip:
        assert narration.audio_uri is not None
        source_range = _range(0, narration.duration_ms)
        item = otio.schema.Clip(
            name="Narration",
            media_reference=otio.schema.ExternalReference(
                target_url=narration.audio_uri,
                available_range=source_range,
            ),
            source_range=source_range,
        )
        item.metadata["clipatlas"] = {
            "narration_track_id": str(narration.id),
            "revision": narration.revision,
        }
        return item

    def _verify_roundtrip(
        self,
        timeline: otio.schema.Timeline,
        metadata: dict[str, object],
        *,
        plan_id: UUID,
        project_id: UUID,
        narration_track_id: UUID,
    ) -> None:
        expected = {
            "plan_id": str(plan_id),
            "project_id": str(project_id),
            "narration_track_id": str(narration_track_id),
        }
        for key, value in expected.items():
            if metadata.get(key) != value:
                raise OtioSerializationError(f"FineCut OTIO verification failed for {key}")
        if _metadata_int(metadata, "timing_rate") != _TIME_RATE:
            raise OtioSerializationError("FineCut OTIO timing rate changed during serialization")
        finecut = _mapping(metadata.get("finecut"))
        if finecut.get("version") != _FINECUT_METADATA_VERSION:
            raise OtioSerializationError("FineCut OTIO metadata is missing")
        duration_ms = finecut.get("duration_ms")
        if isinstance(duration_ms, bool) or not isinstance(duration_ms, int):
            raise OtioSerializationError("FineCut OTIO duration metadata is invalid")
        if len(timeline.video_tracks()) != 1 or len(timeline.audio_tracks()) != 1:
            raise OtioSerializationError("FineCut OTIO track structure changed during serialization")
        video_duration = timeline.video_tracks()[0].duration()
        if video_duration.rate != _TIME_RATE or video_duration.value != duration_ms:
            raise OtioSerializationError("FineCut OTIO video duration changed during serialization")
        total = timeline.duration()
        if total.rate != _TIME_RATE or total.value != _metadata_int(metadata, "total_duration_ms"):
            raise OtioSerializationError("FineCut OTIO total duration changed during serialization")


__all__ = ["FineCutOtioBuilder"]

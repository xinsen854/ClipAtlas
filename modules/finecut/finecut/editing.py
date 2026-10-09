from math import isfinite
from typing import Literal
from uuid import UUID, uuid4

from finecut.models import CandidateItem, Clip, MediaReference, TimelineDocument

_ALLOWED_TRANSFORM_KEYS = frozenset({"position_x", "position_y", "scale", "rotation"})


def can_replace_clip(candidate: CandidateItem, clip: Clip) -> bool:
    return candidate.source_out_ms - candidate.source_in_ms >= clip.duration_ms


def replace_clip(
    document: TimelineDocument,
    target_clip_id: UUID,
    candidate: CandidateItem,
    media: MediaReference,
) -> TimelineDocument:
    if media.media_id != candidate.media_id:
        raise ValueError("media reference does not match candidate")

    updated = document.model_copy(deep=True)
    for track in updated.tracks:
        for index, clip in enumerate(track.clips):
            if clip.id != target_clip_id:
                continue
            if not can_replace_clip(candidate, clip):
                raise ValueError("candidate duration is shorter than timeline slot")
            track.clips[index] = clip.model_copy(
                update={
                    "source_id": str(candidate.media_id),
                    "source_path": media.source_uri,
                    "source_in_ms": candidate.source_in_ms,
                    "source_out_ms": candidate.source_in_ms + clip.duration_ms,
                },
                deep=True,
            )
            return updated

    raise ValueError("target clip not found")


def trim_clip(
    document: TimelineDocument,
    target_clip_id: UUID,
    *,
    edge: Literal["left", "right"],
    delta_ms: int,
) -> TimelineDocument:
    updated = document.model_copy(deep=True)
    for track in updated.tracks:
        for index, clip in enumerate(track.clips):
            if clip.id != target_clip_id:
                continue
            if edge not in ("left", "right"):
                raise ValueError("trim edge must be left or right")
            if delta_ms <= 0 or delta_ms >= clip.duration_ms:
                raise ValueError("trim delta must keep clip duration positive")

            values = {"duration_ms": clip.duration_ms - delta_ms}
            if edge == "left":
                values.update(
                    {
                        "timeline_start_ms": clip.timeline_start_ms + delta_ms,
                        "source_in_ms": clip.source_in_ms + delta_ms,
                    }
                )
            else:
                values["source_out_ms"] = clip.source_out_ms - delta_ms

            track.clips[index] = clip.model_copy(update=values, deep=True)
            return updated

    raise ValueError("target clip not found")


def split_clip(
    document: TimelineDocument,
    target_clip_id: UUID,
    *,
    split_timeline_ms: int,
) -> TimelineDocument:
    updated = document.model_copy(deep=True)
    for track in updated.tracks:
        for index, clip in enumerate(track.clips):
            if clip.id != target_clip_id:
                continue

            clip_end_ms = clip.timeline_start_ms + clip.duration_ms
            if not clip.timeline_start_ms < split_timeline_ms < clip_end_ms:
                raise ValueError("split point must be inside clip")

            left_duration = split_timeline_ms - clip.timeline_start_ms
            right_duration = clip_end_ms - split_timeline_ms
            source_split_ms = clip.source_in_ms + left_duration

            left = clip.model_copy(
                update={
                    "duration_ms": left_duration,
                    "source_out_ms": source_split_ms,
                },
                deep=True,
            )
            right = clip.model_copy(
                update={
                    "id": uuid4(),
                    "timeline_start_ms": split_timeline_ms,
                    "duration_ms": right_duration,
                    "source_in_ms": source_split_ms,
                },
                deep=True,
            )
            track.clips[index : index + 1] = [left, right]
            return updated

    raise ValueError("target clip not found")


def delete_clip(document: TimelineDocument, target_clip_id: UUID) -> TimelineDocument:
    updated = document.model_copy(deep=True)
    for track in updated.tracks:
        for index, clip in enumerate(track.clips):
            if clip.id != target_clip_id:
                continue
            del track.clips[index]
            return updated

    raise ValueError("target clip not found")


def update_clip_properties(
    document: TimelineDocument,
    target_clip_id: UUID,
    *,
    opacity: float | None = None,
    volume: float | None = None,
    transform: dict[str, float] | None = None,
) -> TimelineDocument:
    if opacity is None and volume is None and transform is None:
        raise ValueError("at least one clip property must be provided")
    if opacity is not None and (not isfinite(opacity) or not 0.0 <= opacity <= 1.0):
        raise ValueError("opacity must be between 0 and 1")
    if volume is not None and (not isfinite(volume) or volume < 0.0):
        raise ValueError("volume must be non-negative")

    if transform is not None:
        unsupported = sorted(set(transform) - _ALLOWED_TRANSFORM_KEYS)
        if unsupported:
            raise ValueError(f"unsupported transform key: {unsupported[0]}")
        for key, value in transform.items():
            if not isfinite(value):
                raise ValueError(f"transform {key} must be finite")
        if "scale" in transform and transform["scale"] <= 0.0:
            raise ValueError("scale must be greater than 0")

    updated = document.model_copy(deep=True)
    for track in updated.tracks:
        for index, clip in enumerate(track.clips):
            if clip.id != target_clip_id:
                continue
            values: dict[str, object] = {}
            if opacity is not None:
                values["opacity"] = opacity
            if volume is not None:
                values["volume"] = volume
            if transform is not None:
                merged_transform = dict(clip.transform)
                merged_transform.update(transform)
                values["transform"] = merged_transform
            track.clips[index] = clip.model_copy(update=values, deep=True)
            return updated

    raise ValueError("target clip not found")

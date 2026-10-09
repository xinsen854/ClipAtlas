from itertools import pairwise
from typing import ClassVar

from clipatlas.roughcut.errors import RoughCutTimingError
from clipatlas.roughcut.models import ScriptBeat
from clipatlas.speech.models import (
    NarrationSourceMode,
    NarrationTrack,
    NarrationUnit,
    TimingQuality,
)


def estimate_units_locally(
    track: NarrationTrack, units: list[NarrationUnit],
) -> tuple[NarrationTrack, list[NarrationUnit]]:
    """Allocate a track-only narration locally without claiming ASR accuracy."""
    ordered = sorted(units, key=lambda unit: unit.sequence)
    if not ordered or track.duration_ms <= 0:
        raise RoughCutTimingError("Track-only narration has no text or positive audio duration")
    if track.duration_ms < len(ordered):
        text = " ".join(unit.text.strip() for unit in ordered if unit.text.strip())
        if not text:
            raise RoughCutTimingError("Track-only narration has no usable text")
        ordered = [ordered[0].model_copy(update={"text": text, "sequence": 0})]
    weights = [max(1, len("".join(ch for ch in unit.text if not ch.isspace()))) for unit in ordered]
    total_weight = sum(weights)
    timed = []
    cursor_weight = 0
    for index, (unit, weight) in enumerate(zip(ordered, weights, strict=True)):
        start = 0 if index == 0 else track.duration_ms * cursor_weight // total_weight
        cursor_weight += weight
        end = track.duration_ms if index == len(ordered) - 1 else (
            track.duration_ms * cursor_weight // total_weight
        )
        end = max(start + 1, end)
        timed.append(unit.model_copy(update={"start_ms": start, "end_ms": end}))
    estimated_track = track.model_copy(update={
        "timing_quality": TimingQuality.ESTIMATED,
        "alignment_notes": [
            *track.alignment_notes,
            "旁白仅有整轨时长；粗剪使用本地文本权重估算句子时间，未调用对齐 API",
        ],
    })
    return estimated_track, timed


class BeatBuilder:
    _SUPPORTED_TIMING: ClassVar[frozenset[TimingQuality]] = frozenset(
        {
            TimingQuality.WORD_EXACT,
            TimingQuality.UNIT_EXACT,
            TimingQuality.ALIGNED,
            TimingQuality.ESTIMATED,
        }
    )

    def build(
        self,
        track: NarrationTrack,
        units: list[NarrationUnit],
    ) -> list[ScriptBeat]:
        if track.duration_ms <= 0:
            raise RoughCutTimingError("Narration track duration must be positive")
        if not units:
            raise RoughCutTimingError("Narration track has no timed units")

        ordered = sorted(units, key=lambda unit: unit.sequence)
        seen_sequences: set[int] = set()
        for unit in ordered:
            if unit.track_id != track.id:
                raise RoughCutTimingError("Narration unit belongs to a different track")
            if unit.sequence in seen_sequences:
                raise RoughCutTimingError("Narration unit sequences must be unique")
            seen_sequences.add(unit.sequence)
            if not unit.text.strip():
                raise RoughCutTimingError("Narration unit text must not be empty")

        if track.timing_quality not in self._SUPPORTED_TIMING:
            raise RoughCutTimingError(
                f"Narration timing quality {track.timing_quality.value} "
                "cannot drive automatic rough-cut planning"
            )

        previous_end_ms: int | None = None
        for unit in ordered:
            if unit.start_ms is None or unit.end_ms is None:
                raise RoughCutTimingError("Narration unit is missing authoritative timing")
            if unit.end_ms > track.duration_ms:
                raise RoughCutTimingError("Narration unit extends beyond track duration")
            if previous_end_ms is not None and unit.start_ms < previous_end_ms:
                raise RoughCutTimingError("Narration unit timing overlaps a previous unit")

            previous_end_ms = unit.end_ms

        boundaries = [0]
        for previous, following in pairwise(ordered):
            assert previous.end_ms is not None
            assert following.start_ms is not None
            if following.start_ms == previous.end_ms:
                boundary = previous.end_ms
            else:
                gap_ms = following.start_ms - previous.end_ms
                boundary = previous.end_ms + gap_ms // 2
            boundaries.append(boundary)
        boundaries.append(track.duration_ms)

        beats: list[ScriptBeat] = []
        for index, unit in enumerate(ordered):
            text = unit.text.strip()
            start_ms = boundaries[index]
            end_ms = boundaries[index + 1]
            beats.append(
                ScriptBeat(
                    project_id=track.project_id,
                    narration_track_id=track.id,
                    sequence=unit.sequence,
                    text=text,
                    timeline_start_ms=start_ms,
                    timeline_end_ms=end_ms,
                    target_duration_ms=end_ms - start_ms,
                    query_text=text,
                    retrieval_intent={"timeline_start_ms": start_ms},
                )
            )

        # Preserve sentence-final/topic boundaries. 逗号、顿号、分号延续属于同一句，
        # 只要合计仍是一个正常镜头就共享检索窗口；句号/感叹号/问号是切镜点。
        # 音频单元时间不动。
        _CONTINUATION_END = (",", "，", "、", ";", "；")
        grouped: list[ScriptBeat] = []
        for beat in beats:
            previous_beat = grouped[-1] if grouped else None
            if (previous_beat is not None
                    and previous_beat.text.rstrip().endswith(_CONTINUATION_END)):
                text = previous_beat.text + " " + beat.text
                grouped[-1] = previous_beat.model_copy(update={
                    "text": text, "query_text": text, "timeline_end_ms": beat.timeline_end_ms,
                    "target_duration_ms": beat.timeline_end_ms - previous_beat.timeline_start_ms,
                })
            else:
                grouped.append(beat.model_copy(update={"sequence": len(grouped)}))
        return grouped

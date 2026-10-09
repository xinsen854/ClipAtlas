"""Metadata-only dedup and short-shot merge for a planned rough cut.

No vision analysis and no API calls. Three local rules, applied to the
timeline in order:

  A. same source file, source window strictly ordered and close
     (gap in [0, merge_window_ms)) => same continuous content family:
     the later clip is absorbed into the earlier one (source window
     extended forward, capped at material duration).
  A2. OCR text similarity (when ``ocr_text`` is provided): neighbouring
     clips whose on-screen text overlaps strongly are treated as the same
     screen family and merged, regardless of source position. This catches
     repeated identical screens (same LED panel, same poster) without any
     image analysis.
  B. clips shorter than ``min_keep_ms`` that survived A/A2 try to merge
     into a same-source neighbour (previous preferred, else next).

Total timeline duration is preserved exactly; every clip keeps consistent
source/timeline durations.
"""

from collections.abc import Callable
from uuid import UUID

from clipatlas.roughcut.models import RoughCutClip

MERGE_WINDOW_MS = 20_000
MIN_KEEP_MS = 4_000
OCR_SIMILARITY_THRESHOLD = 0.45

OcrLookup = Callable[[UUID, int, int], str]


def _text_similarity(left: str, right: str) -> float:
    left_chars = {character for character in left if not character.isspace()}
    right_chars = {character for character in right if not character.isspace()}
    if not left_chars or not right_chars:
        return 0.0
    union = left_chars | right_chars
    return len(left_chars & right_chars) / len(union)


class LocalDedupPostProcessor:
    """Merge neighbouring clips that belong to the same source/screen family."""

    def __init__(
        self,
        *,
        merge_window_ms: int = MERGE_WINDOW_MS,
        min_keep_ms: int = MIN_KEEP_MS,
        ocr_similarity_threshold: float = OCR_SIMILARITY_THRESHOLD,
        ocr_text: OcrLookup | None = None,
    ) -> None:
        if merge_window_ms <= 0 or min_keep_ms <= 0:
            raise ValueError("merge_window_ms and min_keep_ms must be positive")
        if not 0.0 <= ocr_similarity_threshold <= 1.0:
            raise ValueError("ocr_similarity_threshold must be within [0, 1]")
        self._merge_window_ms = merge_window_ms
        self._min_keep_ms = min_keep_ms
        self._ocr_similarity_threshold = ocr_similarity_threshold
        self._ocr_text = ocr_text

    def process(
        self,
        clips: list[RoughCutClip],
        source_durations: dict[UUID, int] | None = None,
    ) -> list[RoughCutClip]:
        if not clips:
            return []
        durations = source_durations or {}
        ordered = sorted(clips, key=lambda c: c.timeline_in_ms)

        working: list[tuple[RoughCutClip, int, bool]] = [
            (clip, clip.timeline_out_ms - clip.timeline_in_ms, True) for clip in ordered
        ]

        def cap_ok(video_id: UUID, new_source_end: int) -> bool:
            cap = durations.get(video_id)
            return cap is None or new_source_end <= cap

        def absorb(holder_index: int, victim_index: int, *, ocr_merge: bool) -> None:
            prev, prev_dur, _ = working[holder_index]
            curr, curr_dur, _ = working[victim_index]
            new_source_end = prev.source_out_ms + curr_dur
            if not cap_ok(prev.video_id, new_source_end):
                return
            reason = (
                f"{prev.selection_reason}；本地去重：并入相邻同屏画面"
                if ocr_merge
                else f"{prev.selection_reason}；本地去重：并入相邻同源镜头"
            )
            merged = prev.model_copy(
                update={"source_out_ms": new_source_end, "selection_reason": reason}
            )
            working[holder_index] = (merged, prev_dur + curr_dur, True)
            working[victim_index] = (curr, curr_dur, False)

        def ocr_for(clip: RoughCutClip) -> str:
            if self._ocr_text is None:
                return ""
            try:
                return self._ocr_text(clip.video_id, clip.source_in_ms, clip.source_out_ms)
            except (KeyError, TypeError, ValueError):
                return ""

        # Rule A: ordered same-source close windows.
        index = 0
        while index < len(working) - 1:
            prev, _, prev_kept = working[index]
            curr, _, curr_kept = working[index + 1]
            if not (prev_kept and curr_kept) or prev.video_id != curr.video_id:
                index += 1
                continue
            gap = curr.source_in_ms - prev.source_out_ms
            if not 0 <= gap < self._merge_window_ms:
                index += 1
                continue
            absorb(index, index + 1, ocr_merge=False)
            index += 1

        # Rule A2: OCR-similar neighbouring screens.
        index = 0
        while index < len(working) - 1:
            prev, _, prev_kept = working[index]
            curr, _, curr_kept = working[index + 1]
            if prev_kept and curr_kept and self._ocr_text is not None:
                if _text_similarity(ocr_for(prev), ocr_for(curr)) >= self._ocr_similarity_threshold:
                    absorb(index, index + 1, ocr_merge=True)
            index += 1

        # Rule B: absorb short shots into a same-source neighbour.
        index = 0
        while index < len(working):
            clip, dur, kept = working[index]
            if not kept or dur >= self._min_keep_ms:
                index += 1
                continue
            absorbed = False
            if index > 0:
                prev, prev_dur, prev_kept = working[index - 1]
                if (
                    prev_kept
                    and prev.video_id == clip.video_id
                    and prev.source_out_ms <= clip.source_in_ms
                    and cap_ok(prev.video_id, prev.source_out_ms + dur)
                ):
                    merged = prev.model_copy(
                        update={
                            "source_out_ms": prev.source_out_ms + dur,
                            "selection_reason": (
                                f"{prev.selection_reason}；本地去重：吞并短镜"
                                if prev.selection_reason
                                else "本地去重：吞并短镜"
                            ),
                        }
                    )
                    working[index - 1] = (merged, prev_dur + dur, True)
                    working[index] = (clip, dur, False)
                    absorbed = True
            if not absorbed and index < len(working) - 1:
                nxt, nxt_dur, nxt_kept = working[index + 1]
                if nxt_kept and nxt.video_id == clip.video_id and nxt.source_in_ms - dur >= 0:
                    shifted = nxt.model_copy(
                        update={
                            "source_in_ms": nxt.source_in_ms - dur,
                            "selection_reason": (
                                f"{nxt.selection_reason}；本地去重：吞并短镜"
                                if nxt.selection_reason
                                else "本地去重：吞并短镜"
                            ),
                        }
                    )
                    working[index + 1] = (shifted, nxt_dur + dur, True)
                    working[index] = (clip, dur, False)
                    absorbed = True
            index += 1

        result: list[RoughCutClip] = []
        timeline = 0
        for clip, dur, kept in working:
            if not kept:
                continue
            result.append(
                clip.model_copy(
                    update={
                        "timeline_in_ms": timeline,
                        "timeline_out_ms": timeline + dur,
                    }
                )
            )
            timeline += dur
        return result

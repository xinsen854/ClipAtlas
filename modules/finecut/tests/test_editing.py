from uuid import uuid4

import pytest

from finecut.editing import can_replace_clip, delete_clip, replace_clip, split_clip, trim_clip
from finecut.models import CandidateItem, Clip, MediaReference, TimelineDocument, Track


def _document(*, duration_ms: int = 5000) -> tuple[TimelineDocument, Clip]:
    clip = Clip(
        source_id="original-source",
        source_path="D:/media/original.mp4",
        timeline_start_ms=2000,
        duration_ms=duration_ms,
        source_in_ms=1000,
        source_out_ms=1000 + duration_ms,
    )
    document = TimelineDocument(
        project_id=uuid4(),
        source_plan_id=uuid4(),
        width=1920,
        height=1080,
        fps=30,
        duration_ms=10_000,
        tracks=[Track(kind="video", clips=[clip])],
    )
    return document, clip


def _candidate(*, duration_ms: int, media_id=None) -> CandidateItem:
    media_id = media_id or uuid4()
    return CandidateItem(
        requirement_id="req-1",
        candidate_type="window",
        media_id=media_id,
        source_in_ms=3000,
        source_out_ms=3000 + duration_ms,
        display_level="S",
    )


def test_can_replace_clip_requires_candidate_to_cover_entire_slot() -> None:
    _, clip = _document(duration_ms=5000)
    assert can_replace_clip(_candidate(duration_ms=5000), clip) is True
    assert can_replace_clip(_candidate(duration_ms=4999), clip) is False


def test_replace_clip_preserves_timeline_slot_and_uses_media_reference() -> None:
    document, original = _document(duration_ms=5000)
    candidate = _candidate(duration_ms=7000)
    media = MediaReference(media_id=candidate.media_id, source_uri="D:/media/replacement.mp4")
    replaced = replace_clip(document, original.id, candidate, media)
    assert replaced is not document
    assert document.tracks[0].clips[0] == original
    result = replaced.tracks[0].clips[0]
    assert result.id == original.id
    assert result.timeline_start_ms == original.timeline_start_ms
    assert result.duration_ms == original.duration_ms
    assert result.source_id == str(candidate.media_id)
    assert result.source_path == media.source_uri
    assert result.source_in_ms == candidate.source_in_ms
    assert result.source_out_ms == candidate.source_in_ms + original.duration_ms
    assert result.opacity == original.opacity
    assert result.volume == original.volume
    assert result.transform == original.transform
    assert result.effects == original.effects


def test_replace_clip_rejects_candidate_shorter_than_slot() -> None:
    document, original = _document(duration_ms=5000)
    candidate = _candidate(duration_ms=4999)
    media = MediaReference(media_id=candidate.media_id, source_uri="D:/media/short.mp4")
    with pytest.raises(ValueError, match="candidate duration is shorter than timeline slot"):
        replace_clip(document, original.id, candidate, media)


def test_replace_clip_rejects_mismatched_media_reference() -> None:
    document, original = _document(duration_ms=5000)
    candidate = _candidate(duration_ms=5000)
    media = MediaReference(media_id=uuid4(), source_uri="D:/media/wrong.mp4")
    with pytest.raises(ValueError, match="media reference does not match candidate"):
        replace_clip(document, original.id, candidate, media)


def test_trim_clip_left_keeps_one_to_one_timeline_and_source_relation() -> None:
    document, original = _document(duration_ms=5000)
    trimmed = trim_clip(document, original.id, edge="left", delta_ms=1200)
    assert document.tracks[0].clips[0] == original
    result = trimmed.tracks[0].clips[0]
    assert result.timeline_start_ms == original.timeline_start_ms + 1200
    assert result.duration_ms == original.duration_ms - 1200
    assert result.source_in_ms == original.source_in_ms + 1200
    assert result.source_out_ms == original.source_out_ms


def test_trim_clip_right_keeps_one_to_one_timeline_and_source_relation() -> None:
    document, original = _document(duration_ms=5000)
    trimmed = trim_clip(document, original.id, edge="right", delta_ms=800)
    assert document.tracks[0].clips[0] == original
    result = trimmed.tracks[0].clips[0]
    assert result.timeline_start_ms == original.timeline_start_ms
    assert result.duration_ms == original.duration_ms - 800
    assert result.source_in_ms == original.source_in_ms
    assert result.source_out_ms == original.source_out_ms - 800


@pytest.mark.parametrize("edge,delta_ms", [("left", 0), ("right", 5000), ("middle", 100)])
def test_trim_clip_rejects_invalid_trim(edge: str, delta_ms: int) -> None:
    document, original = _document(duration_ms=5000)
    with pytest.raises(ValueError):
        trim_clip(document, original.id, edge=edge, delta_ms=delta_ms)


def test_split_clip_keeps_timeline_and_source_continuous() -> None:
    document, original = _document(duration_ms=6000)
    split = split_clip(document, original.id, split_timeline_ms=5000)
    assert document.tracks[0].clips[0] == original
    assert len(split.tracks[0].clips) == 2
    left, right = split.tracks[0].clips
    assert left.id == original.id
    assert right.id != original.id
    assert left.timeline_start_ms == 2000
    assert left.duration_ms == 3000
    assert right.timeline_start_ms == 5000
    assert right.duration_ms == 3000
    assert left.timeline_start_ms + left.duration_ms == right.timeline_start_ms
    assert left.source_in_ms == 1000
    assert left.source_out_ms == 4000
    assert right.source_in_ms == 4000
    assert right.source_out_ms == 7000
    assert left.source_out_ms == right.source_in_ms
    assert left.duration_ms + right.duration_ms == original.duration_ms
    assert (left.source_out_ms - left.source_in_ms) + (right.source_out_ms - right.source_in_ms) == original.duration_ms


@pytest.mark.parametrize("split_timeline_ms", [2000, 8000, 1999, 8001])
def test_split_clip_rejects_point_outside_clip_interior(split_timeline_ms: int) -> None:
    document, original = _document(duration_ms=6000)
    with pytest.raises(ValueError, match="split point must be inside clip"):
        split_clip(document, original.id, split_timeline_ms=split_timeline_ms)


def test_delete_clip_removes_only_target_without_ripple() -> None:
    document, target = _document(duration_ms=2000)
    untouched = Clip(
        source_id="second-source",
        source_path="D:/media/second.mp4",
        timeline_start_ms=6000,
        duration_ms=2000,
        source_in_ms=500,
        source_out_ms=2500,
    )
    document.tracks[0].clips.append(untouched)

    deleted = delete_clip(document, target.id)

    assert [clip.id for clip in document.tracks[0].clips] == [target.id, untouched.id]
    assert [clip.id for clip in deleted.tracks[0].clips] == [untouched.id]
    result = deleted.tracks[0].clips[0]
    assert result.timeline_start_ms == untouched.timeline_start_ms
    assert result.duration_ms == untouched.duration_ms
    assert result.source_in_ms == untouched.source_in_ms
    assert result.source_out_ms == untouched.source_out_ms


def test_delete_clip_rejects_unknown_target() -> None:
    document, _ = _document()
    with pytest.raises(ValueError, match="target clip not found"):
        delete_clip(document, uuid4())

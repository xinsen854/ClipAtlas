from uuid import uuid4

import pytest
from pydantic import ValidationError

from finecut.models import Clip, TimelineDocument, Track


def make_clip(**overrides: object) -> Clip:
    values: dict[str, object] = {
        "source_id": "segment-1",
        "source_path": "D:/media/source.mp4",
        "timeline_start_ms": 1_000,
        "duration_ms": 2_000,
        "source_in_ms": 5_000,
        "source_out_ms": 7_000,
    }
    values.update(overrides)
    return Clip(**values)


def test_clip_requires_matching_source_and_timeline_duration() -> None:
    with pytest.raises(ValidationError, match="source duration must match duration_ms"):
        make_clip(source_out_ms=7_500)


def test_track_rejects_unknown_kind() -> None:
    with pytest.raises(ValidationError):
        Track(id=uuid4(), kind="unknown", clips=[])


def test_timeline_document_rejects_clip_past_document_duration() -> None:
    clip = make_clip(timeline_start_ms=4_000, duration_ms=2_000)
    track = Track(kind="video", clips=[clip])

    with pytest.raises(ValidationError, match="clip exceeds document duration"):
        TimelineDocument(
            project_id=uuid4(),
            source_plan_id=uuid4(),
            width=1920,
            height=1080,
            fps=30.0,
            duration_ms=5_000,
            tracks=[track],
        )


def test_timeline_document_preserves_minimal_clip_fields() -> None:
    clip = make_clip()
    track = Track(kind="video", clips=[clip])
    document = TimelineDocument(
        project_id=uuid4(),
        source_plan_id=uuid4(),
        width=1920,
        height=1080,
        fps=30.0,
        duration_ms=10_000,
        tracks=[track],
    )

    assert document.version == 1
    assert document.tracks[0].clips[0].source_in_ms == 5_000
    assert document.tracks[0].clips[0].source_out_ms == 7_000
    assert document.tracks[0].clips[0].timeline_start_ms == 1_000
    assert document.tracks[0].clips[0].duration_ms == 2_000

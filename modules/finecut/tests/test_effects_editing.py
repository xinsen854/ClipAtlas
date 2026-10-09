from uuid import uuid4

import pytest

from finecut.editing import update_clip_properties
from finecut.models import Clip, TimelineDocument, Track


def _document() -> tuple[TimelineDocument, Clip]:
    clip = Clip(
        source_id="source-a",
        source_path="D:/media/source-a.mp4",
        timeline_start_ms=0,
        duration_ms=5000,
        source_in_ms=1000,
        source_out_ms=6000,
        opacity=1.0,
        volume=1.0,
        transform={"legacy": 3.0},
    )
    document = TimelineDocument(
        project_id=uuid4(),
        source_plan_id=uuid4(),
        width=1920,
        height=1080,
        fps=30,
        duration_ms=5000,
        tracks=[Track(kind="video", clips=[clip])],
    )
    return document, clip


def test_update_clip_properties_returns_new_document_and_merges_transform() -> None:
    document, original = _document()
    updated = update_clip_properties(
        document,
        original.id,
        opacity=0.55,
        volume=0.35,
        transform={
            "position_x": 24.0,
            "position_y": -12.0,
            "scale": 1.25,
            "rotation": 15.0,
        },
    )

    assert updated is not document
    assert document.tracks[0].clips[0] == original
    result = updated.tracks[0].clips[0]
    assert result.opacity == 0.55
    assert result.volume == 0.35
    assert result.transform == {
        "legacy": 3.0,
        "position_x": 24.0,
        "position_y": -12.0,
        "scale": 1.25,
        "rotation": 15.0,
    }
    assert result.effects == original.effects
    assert result.source_id == original.source_id
    assert result.timeline_start_ms == original.timeline_start_ms


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"opacity": -0.01}, "opacity must be between 0 and 1"),
        ({"opacity": 1.01}, "opacity must be between 0 and 1"),
        ({"volume": -0.01}, "volume must be non-negative"),
        ({"transform": {"scale": 0.0}}, "scale must be greater than 0"),
        ({"transform": {"anchor_x": 1.0}}, "unsupported transform key"),
        ({}, "at least one clip property must be provided"),
    ],
)
def test_update_clip_properties_rejects_invalid_property_edits(
    kwargs: dict[str, object],
    message: str,
) -> None:
    document, clip = _document()
    with pytest.raises(ValueError, match=message):
        update_clip_properties(document, clip.id, **kwargs)


def test_update_clip_properties_rejects_unknown_target() -> None:
    document, _ = _document()
    with pytest.raises(ValueError, match="target clip not found"):
        update_clip_properties(document, uuid4(), opacity=0.5)

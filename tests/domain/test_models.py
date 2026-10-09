from uuid import uuid4

import pytest
from pydantic import ValidationError

from clipatlas.domain import models
from clipatlas.domain.models import (
    AnnotationOrigin,
    SegmentSource,
    SemanticAnnotation,
    VideoSegment,
)


def test_valid_segment_preserves_integer_millisecond_boundaries():
    segment = VideoSegment(
        video_id=uuid4(),
        start_ms=1234,
        end_ms=5678,
        source=SegmentSource.SCENE_DETECTION,
    )

    assert segment.start_ms == 1234
    assert segment.end_ms == 5678


def test_segment_rejects_non_positive_range():
    with pytest.raises(ValidationError):
        VideoSegment(
            video_id=uuid4(),
            start_ms=1000,
            end_ms=1000,
            source=SegmentSource.AI,
        )


def test_segment_rejects_negative_start():
    with pytest.raises(ValidationError):
        VideoSegment(
            video_id=uuid4(),
            start_ms=-1,
            end_ms=1000,
            source=SegmentSource.MANUAL,
        )


def test_annotation_rejects_confidence_outside_unit_interval():
    with pytest.raises(ValidationError):
        SemanticAnnotation(
            segment_id=uuid4(),
            origin=AnnotationOrigin.AI,
            description="x",
            confidence=1.1,
        )


def test_human_annotation_does_not_require_provider_or_model():
    annotation = SemanticAnnotation(
        segment_id=uuid4(),
        origin=AnnotationOrigin.HUMAN,
        description="Human corrected description",
    )

    assert annotation.provider is None
    assert annotation.model is None
    assert annotation.revision == 1
    assert annotation.verified is False
    assert annotation.locked is False


def test_video_asset_has_clipatlas_owned_identity_and_utc_timestamp():
    video_asset_type = getattr(models, "VideoAsset", None)
    assert video_asset_type is not None
    asset = video_asset_type(filename="source.mp4", source_uri="file:///source.mp4")
    assert asset.id is not None
    assert asset.created_at.tzinfo is not None

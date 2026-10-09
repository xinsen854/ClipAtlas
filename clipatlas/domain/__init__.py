"""Canonical ClipAtlas domain models."""

from .models import AnnotationOrigin, SegmentSource, SemanticAnnotation, VideoAsset, VideoSegment
from .visual_protocol import ScriptVisualRequirement, VideoSequenceWindow, VideoTimelineEvent
from .vehicle_names import canonical_vehicle_name, is_known_vehicle_name

__all__ = [
    "AnnotationOrigin",
    "SegmentSource",
    "SemanticAnnotation",
    "VideoAsset",
    "VideoSegment",
    "ScriptVisualRequirement",
    "VideoSequenceWindow",
    "VideoTimelineEvent",
    "canonical_vehicle_name",
    "is_known_vehicle_name",
]

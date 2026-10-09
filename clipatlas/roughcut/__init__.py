"""Canonical script-to-rough-cut planning domain for ClipAtlas."""

from clipatlas.roughcut.contracts import SegmentSearch
from clipatlas.roughcut.errors import (
    RoughCutConfigurationError,
    RoughCutError,
    RoughCutPlanningError,
    RoughCutPlanNotFoundError,
    RoughCutRetrievalError,
    RoughCutTimingError,
    RoughCutUnavailableError,
)
from clipatlas.roughcut.models import (
    CandidateScore,
    PlannerSettings,
    RoughCutClip,
    RoughCutPlan,
    ScriptBeat,
)

__all__ = [
    "CandidateScore",
    "PlannerSettings",
    "RoughCutClip",
    "RoughCutConfigurationError",
    "RoughCutError",
    "RoughCutPlan",
    "RoughCutPlanNotFoundError",
    "RoughCutPlanningError",
    "RoughCutRetrievalError",
    "RoughCutTimingError",
    "RoughCutUnavailableError",
    "ScriptBeat",
    "SegmentSearch",
]

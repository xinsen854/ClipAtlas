class RoughCutError(RuntimeError):
    """Base error for canonical rough-cut planning."""


class RoughCutConfigurationError(RoughCutError):
    """Raised when a project is missing required rough-cut inputs."""


class RoughCutTimingError(RoughCutError):
    """Raised when narration timing cannot safely drive an automatic rough cut."""


class RoughCutRetrievalError(RoughCutError):
    """Raised when semantic footage retrieval cannot provide usable candidates."""


class RoughCutPlanningError(RoughCutError):
    """Raised when a candidate plan violates canonical planning invariants."""


class RoughCutUnavailableError(RoughCutError):
    """Raised when automatic rough-cut runtime is not configured."""


class RoughCutPlanNotFoundError(RoughCutError):
    """Raised when a requested rough-cut plan does not exist."""

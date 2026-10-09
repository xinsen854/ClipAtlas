class TimelineExportError(RuntimeError):
    """Base error for timeline export operations."""


class ExportPlanNotFoundError(TimelineExportError):
    """Raised when a requested persisted rough-cut plan does not exist."""


class ExportNotReadyError(TimelineExportError):
    """Raised when a persisted plan cannot yet be exported safely."""


class ExportInvariantError(TimelineExportError):
    """Raised when canonical timeline invariants are violated."""


class OtioSerializationError(TimelineExportError):
    """Raised when native OTIO serialization or verification fails."""


class JianyingError(TimelineExportError):
    """Base error for Jianying draft export operations."""


class JianyingUnavailableError(JianyingError):
    """Raised when no Jianying backend is available at runtime."""


class JianyingDependencyError(JianyingError):
    """Raised when an optional Jianying backend dependency is missing."""


class JianyingConfigurationError(JianyingError):
    """Raised when Jianying export configuration is incomplete or invalid."""


class JianyingMediaError(JianyingError):
    """Raised when OTIO references media Jianying V0.1 cannot consume."""


class JianyingTimeError(JianyingError):
    """Raised when OTIO timing cannot map losslessly to Jianying microseconds."""


class JianyingWriteError(JianyingError):
    """Raised when the Jianying backend cannot create or save a draft."""

class SpeechError(Exception):
    """Base error for provider-neutral speech operations."""


class SpeechAuthenticationError(SpeechError):
    """Raised when a speech provider rejects authentication."""


class SpeechRateLimitError(SpeechError):
    """Raised when a speech provider rate limit is reached."""


class SpeechRequestError(SpeechError):
    """Raised when a speech provider request fails."""


class SpeechConfigurationError(SpeechError):
    """Raised when speech configuration is invalid or incomplete."""


class SpeechAudioValidationError(SpeechError):
    """Raised when speech audio cannot be validated or normalized."""


class SpeechProfileNotFoundError(SpeechError):
    """Raised when a requested speech profile does not exist."""


class SpeechProviderUnavailableError(SpeechError):
    """Raised when the configured speech runtime is unavailable."""

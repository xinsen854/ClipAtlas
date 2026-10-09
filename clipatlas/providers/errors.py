class ProviderError(Exception):
    """Base provider-layer error."""


class ProviderNotFoundError(ProviderError):
    pass


class ProviderCapabilityError(ProviderError):
    pass


class ProviderRequestError(ProviderError):
    pass


class ProviderStructuredOutputError(ProviderRequestError):
    """The provider answered, but its content cannot be used as an annotation."""


class ProviderAuthenticationError(ProviderError):
    pass


class ProviderRateLimitError(ProviderError):
    retry_after: float = 0.0

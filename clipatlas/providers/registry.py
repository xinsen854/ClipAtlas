from clipatlas.providers.contracts import (
    ProviderCapabilities,
    ProviderDescriptor,
    VideoUnderstandingProvider,
)
from clipatlas.providers.errors import ProviderNotFoundError


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, VideoUnderstandingProvider] = {}

    def register(self, provider: VideoUnderstandingProvider) -> None:
        if provider.name in self._providers:
            raise ValueError(f"provider '{provider.name}' is already registered")
        self._providers[provider.name] = provider

    def get(self, name: str) -> VideoUnderstandingProvider:
        try:
            return self._providers[name]
        except KeyError as exc:
            raise ProviderNotFoundError(f"provider '{name}' was not found") from exc

    def list_descriptors(self) -> list[ProviderDescriptor]:
        return [
            ProviderDescriptor(name=provider.name, capabilities=provider.capabilities)
            for provider in self._providers.values()
        ]

    def find(self, required: ProviderCapabilities) -> list[VideoUnderstandingProvider]:
        required_flags = [
            name for name, value in required.model_dump().items() if value is True
        ]
        return [
            provider
            for provider in self._providers.values()
            if all(getattr(provider.capabilities, flag) for flag in required_flags)
        ]

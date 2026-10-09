from pydantic import BaseModel

from clipatlas.speech.contracts import SpeechProvider, SpeechProviderCapabilities


class SpeechProviderDescriptor(BaseModel):
    name: str
    model: str
    capabilities: SpeechProviderCapabilities


class SpeechProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, SpeechProvider] = {}

    def register(self, provider: SpeechProvider) -> None:
        if provider.name in self._providers:
            raise ValueError(f"Speech provider already registered: {provider.name}")
        self._providers[provider.name] = provider

    def get(self, name: str) -> SpeechProvider:
        try:
            return self._providers[name]
        except KeyError as exc:
            raise KeyError(f"Unknown speech provider: {name}") from exc

    def list_descriptors(self) -> list[SpeechProviderDescriptor]:
        return [
            SpeechProviderDescriptor(
                name=provider.name,
                model=provider.model,
                capabilities=provider.capabilities,
            )
            for provider in self._providers.values()
        ]

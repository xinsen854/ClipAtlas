import pytest

from clipatlas.speech.fake import FakeSpeechProvider
from clipatlas.speech.registry import SpeechProviderRegistry


def test_speech_registry_registers_gets_and_lists_descriptors() -> None:
    registry = SpeechProviderRegistry()
    provider = FakeSpeechProvider()

    registry.register(provider)

    assert registry.get("fake") is provider
    descriptors = registry.list_descriptors()
    assert len(descriptors) == 1
    assert descriptors[0].name == "fake"
    assert descriptors[0].model == "fake-tts-v0.1"
    assert descriptors[0].capabilities.preset_voices is True


def test_speech_registry_rejects_duplicate_provider_name() -> None:
    registry = SpeechProviderRegistry()
    registry.register(FakeSpeechProvider())

    with pytest.raises(ValueError, match="already registered"):
        registry.register(FakeSpeechProvider(model="another-model"))


def test_speech_registry_unknown_provider_raises_key_error() -> None:
    registry = SpeechProviderRegistry()

    with pytest.raises(KeyError, match="missing"):
        registry.get("missing")

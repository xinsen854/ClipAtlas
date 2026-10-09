from clipatlas.speech.contracts import SpeechProvider, SpeechProviderCapabilities
from clipatlas.speech.models import (
    SpeechSynthesisRequest,
    SpeechSynthesisResult,
    VoiceDescriptor,
)


class DummySpeechProvider:
    @property
    def name(self) -> str:
        return "dummy"

    @property
    def model(self) -> str:
        return "dummy-tts"

    @property
    def capabilities(self) -> SpeechProviderCapabilities:
        return SpeechProviderCapabilities(preset_voices=True)

    async def list_voices(self) -> list[VoiceDescriptor]:
        return []

    async def synthesize(self, request: SpeechSynthesisRequest) -> SpeechSynthesisResult:
        return SpeechSynthesisResult(
            provider=self.name,
            model=self.model,
            audio_bytes=b"RIFF",
            output_format="wav",
        )


def test_capabilities_default_to_false() -> None:
    capabilities = SpeechProviderCapabilities()

    assert capabilities.speed_control is False
    assert capabilities.pitch_control is False
    assert capabilities.emotion_control is False
    assert capabilities.word_timestamps is False
    assert capabilities.languages == []


def test_provider_protocol_is_runtime_checkable() -> None:
    assert isinstance(DummySpeechProvider(), SpeechProvider)

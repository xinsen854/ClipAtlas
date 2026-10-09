import io
import wave

from clipatlas.speech.contracts import SpeechProviderCapabilities
from clipatlas.speech.errors import SpeechRequestError
from clipatlas.speech.models import (
    AgeStyle,
    SpeechSynthesisRequest,
    SpeechSynthesisResult,
    VoiceDescriptor,
    VoiceGender,
)
from clipatlas.speech.request_policy import filter_supported_controls


class FakeSpeechProvider:
    def __init__(self, model: str = "fake-tts-v0.1") -> None:
        self._model = model
        self._capabilities = SpeechProviderCapabilities(
            preset_voices=True,
            voice_metadata=True,
            speed_control=True,
            languages=["zh-CN", "en-US"],
        )

    @property
    def name(self) -> str:
        return "fake"

    @property
    def model(self) -> str:
        return self._model

    @property
    def capabilities(self) -> SpeechProviderCapabilities:
        return self._capabilities

    async def list_voices(self) -> list[VoiceDescriptor]:
        return [
            VoiceDescriptor(
                provider=self.name,
                voice_id="fake-female",
                display_name="Fake Female",
                gender=VoiceGender.FEMALE,
                age_style=AgeStyle.YOUNG,
                languages=["zh-CN", "en-US"],
                tags=["test"],
            ),
            VoiceDescriptor(
                provider=self.name,
                voice_id="fake-male",
                display_name="Fake Male",
                gender=VoiceGender.MALE,
                age_style=AgeStyle.MATURE,
                languages=["zh-CN", "en-US"],
                tags=["test"],
            ),
        ]

    async def synthesize(self, request: SpeechSynthesisRequest) -> SpeechSynthesisResult:
        if request.output_format.lower() != "wav":
            raise SpeechRequestError("Fake speech provider only supports wav output")

        filtered = filter_supported_controls(request, self.capabilities)
        sample_rate = filtered.sample_rate or 48000
        speed = filtered.speed or 1.0
        duration_ms = max(200, round((200 + len(filtered.text) * 80) / speed))
        frame_count = max(1, round(sample_rate * duration_ms / 1000))

        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(b"\x00\x00" * frame_count)

        return SpeechSynthesisResult(
            provider=self.name,
            model=self.model,
            audio_bytes=buffer.getvalue(),
            output_format="wav",
            sample_rate=sample_rate,
            duration_ms=duration_ms,
            raw_payload={
                "voice_id": filtered.voice_id,
                "language": filtered.language,
                "speed": filtered.speed,
                "pitch": filtered.pitch,
                "volume": filtered.volume,
                "emotion": filtered.emotion,
                "style": filtered.style,
                "instruction": filtered.instruction,
            },
        )

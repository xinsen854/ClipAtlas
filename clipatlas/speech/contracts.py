from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from clipatlas.speech.models import (
    SpeechSynthesisRequest,
    SpeechSynthesisResult,
    VoiceDescriptor,
)


class SpeechProviderCapabilities(BaseModel):
    preset_voices: bool = False
    voice_metadata: bool = False
    speed_control: bool = False
    pitch_control: bool = False
    volume_control: bool = False
    emotion_control: bool = False
    instruction_control: bool = False
    voice_clone: bool = False
    voice_design: bool = False
    word_timestamps: bool = False
    streaming: bool = False
    languages: list[str] = Field(default_factory=list)


@runtime_checkable
class SpeechProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def model(self) -> str: ...

    @property
    def capabilities(self) -> SpeechProviderCapabilities: ...

    async def list_voices(self) -> list[VoiceDescriptor]: ...

    async def synthesize(self, request: SpeechSynthesisRequest) -> SpeechSynthesisResult: ...

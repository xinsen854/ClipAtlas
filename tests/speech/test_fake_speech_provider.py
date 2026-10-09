import asyncio
import io
import wave

from clipatlas.speech.contracts import SpeechProvider
from clipatlas.speech.fake import FakeSpeechProvider
from clipatlas.speech.models import SpeechSynthesisRequest


def test_fake_provider_is_protocol_compatible_and_lists_stable_voices() -> None:
    provider = FakeSpeechProvider()

    voices = asyncio.run(provider.list_voices())

    assert isinstance(provider, SpeechProvider)
    assert provider.name == "fake"
    assert provider.model == "fake-tts-v0.1"
    assert [voice.voice_id for voice in voices] == ["fake-female", "fake-male"]


def test_fake_provider_returns_deterministic_valid_pcm_wav() -> None:
    provider = FakeSpeechProvider()
    request = SpeechSynthesisRequest(
        text="这是一句测试旁白。",
        voice_id="fake-female",
        language="zh-CN",
        speed=1.0,
        pitch=2.0,
        emotion="serious",
        instruction="restrained",
        output_format="wav",
        sample_rate=48000,
    )

    first = asyncio.run(provider.synthesize(request))
    second = asyncio.run(provider.synthesize(request))

    assert first.audio_bytes == second.audio_bytes
    assert first.provider == "fake"
    assert first.model == "fake-tts-v0.1"
    assert first.output_format == "wav"
    assert first.sample_rate == 48000
    assert first.duration_ms is not None
    assert first.duration_ms > 0

    with wave.open(io.BytesIO(first.audio_bytes), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == 48000
        assert wav_file.getnframes() > 0


def test_fake_provider_filters_controls_using_its_capabilities() -> None:
    provider = FakeSpeechProvider()
    request = SpeechSynthesisRequest(
        text="测试",
        voice_id="fake-male",
        speed=1.1,
        pitch=3.0,
        volume=0.7,
        emotion="angry",
        style="dramatic",
        instruction="shout",
    )

    result = asyncio.run(provider.synthesize(request))

    assert result.raw_payload["speed"] == 1.1
    assert result.raw_payload["pitch"] is None
    assert result.raw_payload["volume"] is None
    assert result.raw_payload["emotion"] is None
    assert result.raw_payload["style"] is None
    assert result.raw_payload["instruction"] is None

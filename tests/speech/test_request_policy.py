from clipatlas.speech.contracts import SpeechProviderCapabilities
from clipatlas.speech.models import SpeechSynthesisRequest
from clipatlas.speech.request_policy import filter_supported_controls


def test_filter_supported_controls_keeps_only_enabled_controls() -> None:
    request = SpeechSynthesisRequest(
        text="测试旁白",
        voice_id="voice-a",
        language="zh-CN",
        speed=1.08,
        pitch=1.5,
        volume=0.9,
        emotion="serious",
        style="documentary",
        instruction="calm and restrained",
        output_format="wav",
        sample_rate=48000,
    )
    capabilities = SpeechProviderCapabilities(speed_control=True)

    filtered = filter_supported_controls(request, capabilities)

    assert filtered.text == request.text
    assert filtered.voice_id == request.voice_id
    assert filtered.language == request.language
    assert filtered.speed == 1.08
    assert filtered.pitch is None
    assert filtered.volume is None
    assert filtered.emotion is None
    assert filtered.style is None
    assert filtered.instruction is None
    assert filtered.output_format == "wav"
    assert filtered.sample_rate == 48000


def test_instruction_capability_controls_style_and_instruction_together() -> None:
    request = SpeechSynthesisRequest(
        text="测试旁白",
        voice_id="voice-a",
        style="documentary",
        instruction="calm and restrained",
    )

    filtered = filter_supported_controls(
        request,
        SpeechProviderCapabilities(instruction_control=True),
    )

    assert filtered.style == "documentary"
    assert filtered.instruction == "calm and restrained"

from clipatlas.speech.contracts import SpeechProviderCapabilities
from clipatlas.speech.models import SpeechSynthesisRequest


def filter_supported_controls(
    request: SpeechSynthesisRequest,
    capabilities: SpeechProviderCapabilities,
) -> SpeechSynthesisRequest:
    """Return a copy with provider-unsupported expressive controls removed."""
    return request.model_copy(
        update={
            "speed": request.speed if capabilities.speed_control else None,
            "pitch": request.pitch if capabilities.pitch_control else None,
            "volume": request.volume if capabilities.volume_control else None,
            "emotion": request.emotion if capabilities.emotion_control else None,
            "style": request.style if capabilities.instruction_control else None,
            "instruction": request.instruction if capabilities.instruction_control else None,
        }
    )

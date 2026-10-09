from typing import Any
from urllib.parse import urlparse

import httpx

from clipatlas.speech.contracts import SpeechProviderCapabilities
from clipatlas.speech.errors import (
    SpeechAuthenticationError,
    SpeechConfigurationError,
    SpeechRateLimitError,
    SpeechRequestError,
)
from clipatlas.speech.models import (
    SpeechSynthesisRequest,
    SpeechSynthesisResult,
    VoiceDescriptor,
)
from clipatlas.speech.request_policy import filter_supported_controls

_DEFAULT_ENDPOINT = (
    "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer"
)
_DEFAULT_MAX_AUDIO_BYTES = 50 * 1024 * 1024
_ALLOWED_FORMATS = {"mp3", "pcm", "wav", "opus"}
_ALLOWED_SAMPLE_RATES = {8000, 16000, 22050, 24000, 44100, 48000}
_SUPPORTED_LANGUAGE_HINTS = {
    "zh",
    "en",
    "fr",
    "de",
    "ja",
    "ko",
    "ru",
    "pt",
    "th",
    "id",
    "vi",
}


class DashScopeSpeechProvider:
    """Non-streaming HTTP adapter for DashScope CosyVoice speech synthesis."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "cosyvoice-v3.5-flash",
        base_url: str = _DEFAULT_ENDPOINT,
        client: httpx.AsyncClient | None = None,
        max_audio_bytes: int = _DEFAULT_MAX_AUDIO_BYTES,
    ) -> None:
        if max_audio_bytes <= 0:
            raise SpeechConfigurationError("DashScope maximum audio size must be positive")
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._client = client
        self._max_audio_bytes = max_audio_bytes
        self._capabilities = SpeechProviderCapabilities(
            preset_voices=False,
            voice_metadata=False,
            speed_control=True,
            pitch_control=True,
            volume_control=True,
            emotion_control=False,
            instruction_control=True,
            voice_clone=True,
            voice_design=True,
            word_timestamps=False,
            streaming=False,
            languages=sorted(_SUPPORTED_LANGUAGE_HINTS),
        )

    @property
    def name(self) -> str:
        return "dashscope"

    @property
    def model(self) -> str:
        return self._model

    @property
    def capabilities(self) -> SpeechProviderCapabilities:
        return self._capabilities

    async def list_voices(self) -> list[VoiceDescriptor]:
        # CosyVoice v3.5 has no system voices. Custom voice enrollment is a
        # separate vendor API and is intentionally outside this adapter.
        return []

    @staticmethod
    def _normalize_language_hint(language: str | None) -> str | None:
        if language is None:
            return None
        normalized = language.strip().lower().replace("_", "-").split("-", 1)[0]
        if normalized not in _SUPPORTED_LANGUAGE_HINTS:
            raise SpeechConfigurationError(f"Unsupported DashScope language: {language}")
        return normalized

    @staticmethod
    def _validate_request(request: SpeechSynthesisRequest) -> None:
        output_format = request.output_format.lower()
        if output_format not in _ALLOWED_FORMATS:
            raise SpeechConfigurationError(
                f"Unsupported DashScope output format: {request.output_format}"
            )
        sample_rate = request.sample_rate or 48000
        if sample_rate not in _ALLOWED_SAMPLE_RATES:
            raise SpeechConfigurationError(
                f"Unsupported DashScope sample rate: {sample_rate}"
            )
        if request.speed is not None and not 0.5 <= request.speed <= 2.0:
            raise SpeechConfigurationError("DashScope speed must be between 0.5 and 2.0")
        if request.pitch is not None and not 0.5 <= request.pitch <= 2.0:
            raise SpeechConfigurationError("DashScope pitch must be between 0.5 and 2.0")
        if request.volume is not None and not 0.0 <= request.volume <= 2.0:
            raise SpeechConfigurationError("DashScope volume ratio must be between 0.0 and 2.0")

    def _build_payload(self, request: SpeechSynthesisRequest) -> dict[str, Any]:
        filtered = filter_supported_controls(request, self.capabilities)
        self._validate_request(filtered)
        language_hint = self._normalize_language_hint(filtered.language)
        sample_rate = filtered.sample_rate or 48000

        input_payload: dict[str, Any] = {
            "text": filtered.text,
            "voice": filtered.voice_id,
            "format": filtered.output_format.lower(),
            "sample_rate": sample_rate,
        }
        if filtered.volume is not None:
            input_payload["volume"] = round(filtered.volume * 50)
        if filtered.speed is not None:
            input_payload["rate"] = filtered.speed
        if filtered.pitch is not None:
            input_payload["pitch"] = filtered.pitch
        if language_hint is not None:
            input_payload["language_hints"] = [language_hint]
        instruction = filtered.instruction or filtered.style
        if instruction is not None:
            input_payload["instruction"] = instruction

        return {"model": self.model, "input": input_payload}

    @staticmethod
    def _vendor_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text[:500]
        if isinstance(payload, dict):
            for key in ("message", "error_message", "code"):
                value = payload.get(key)
                if value:
                    return str(value)
        return response.text[:500]

    def _raise_for_vendor_status(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        message = self._vendor_message(response) or f"HTTP {response.status_code}"
        if response.status_code in (401, 403):
            raise SpeechAuthenticationError(message)
        if response.status_code == 429:
            raise SpeechRateLimitError(message)
        raise SpeechRequestError(message)

    @staticmethod
    def _audio_url(payload: Any) -> str:
        if not isinstance(payload, dict):
            raise SpeechRequestError("DashScope returned malformed response payload")
        output = payload.get("output")
        if not isinstance(output, dict):
            raise SpeechRequestError("DashScope response is missing output")
        audio = output.get("audio")
        if not isinstance(audio, dict):
            raise SpeechRequestError("DashScope response is missing audio metadata")
        url = audio.get("url")
        if not isinstance(url, str) or not url.strip():
            raise SpeechRequestError("DashScope response is missing audio URL")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise SpeechRequestError("DashScope returned an unsafe audio URL")
        return url

    async def _read_bounded_audio(self, response: httpx.Response) -> bytes:
        content_length = response.headers.get("content-length")
        if content_length is not None:
            try:
                declared_size = int(content_length)
            except ValueError:
                declared_size = 0
            if declared_size > self._max_audio_bytes:
                raise SpeechRequestError("DashScope audio exceeds maximum audio size")

        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > self._max_audio_bytes:
                raise SpeechRequestError("DashScope audio exceeds maximum audio size")
            chunks.append(chunk)
        return b"".join(chunks)

    async def _synthesize_with_client(
        self,
        client: httpx.AsyncClient,
        request: SpeechSynthesisRequest,
    ) -> SpeechSynthesisResult:
        payload = self._build_payload(request)
        try:
            response = await client.post(
                self._base_url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
            )
            self._raise_for_vendor_status(response)
            try:
                vendor_payload: Any = response.json()
            except ValueError as exc:
                raise SpeechRequestError("DashScope returned invalid JSON") from exc

            audio_url = self._audio_url(vendor_payload)
            async with client.stream("GET", audio_url, follow_redirects=False) as audio_response:
                if audio_response.status_code >= 400:
                    await audio_response.aread()
                    self._raise_for_vendor_status(audio_response)
                audio_bytes = await self._read_bounded_audio(audio_response)
        except httpx.RequestError as exc:
            raise SpeechRequestError(str(exc)) from exc

        if not audio_bytes:
            raise SpeechRequestError("DashScope returned empty audio")

        return SpeechSynthesisResult(
            provider=self.name,
            model=self.model,
            audio_bytes=audio_bytes,
            output_format=request.output_format.lower(),
            sample_rate=request.sample_rate or 48000,
            duration_ms=None,
            raw_payload=vendor_payload if isinstance(vendor_payload, dict) else {},
        )

    async def synthesize(self, request: SpeechSynthesisRequest) -> SpeechSynthesisResult:
        if self._client is not None:
            return await self._synthesize_with_client(self._client, request)
        async with httpx.AsyncClient(timeout=60.0) as client:
            return await self._synthesize_with_client(client, request)

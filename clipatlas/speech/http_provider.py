import base64
import binascii
import ipaddress
import json
import re
from enum import Enum
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field

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

_ALLOWED_METHODS = {"POST", "PUT"}
_ALLOWED_REQUEST_FIELDS = {
    "text",
    "voice_id",
    "language",
    "speed",
    "pitch",
    "volume",
    "emotion",
    "style",
    "instruction",
    "output_format",
    "sample_rate",
}
_VENDOR_FIELD_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


class HttpSpeechResponseMode(str, Enum):
    BYTES = "bytes"
    BASE64 = "base64"
    URL = "url"


class HttpSpeechProviderConfig(BaseModel):
    name: str
    model: str
    endpoint: str
    method: str = "POST"
    headers: dict[str, str] = Field(default_factory=dict)
    field_mappings: dict[str, str] = Field(default_factory=dict)
    response_mode: HttpSpeechResponseMode = HttpSpeechResponseMode.BYTES
    response_field: str | None = None
    timeout_seconds: float = 30.0
    max_response_bytes: int = 50 * 1024 * 1024
    output_format: str = "wav"
    sample_rate: int = 48000
    capabilities: SpeechProviderCapabilities = Field(default_factory=SpeechProviderCapabilities)


class GenericHttpSpeechProvider:
    def __init__(
        self,
        *,
        config: HttpSpeechProviderConfig,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config
        self._client = client
        self._validate_config(local_only=False)

    @property
    def name(self) -> str:
        return self._config.name

    @property
    def model(self) -> str:
        return self._config.model

    @property
    def capabilities(self) -> SpeechProviderCapabilities:
        return self._config.capabilities

    async def list_voices(self) -> list[VoiceDescriptor]:
        return []

    @staticmethod
    def _validate_http_url(url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise SpeechConfigurationError("HTTP speech endpoint must use http or https")
        if parsed.username is not None or parsed.password is not None:
            raise SpeechConfigurationError("HTTP speech endpoint must not contain user info")

    @staticmethod
    def _is_loopback_url(url: str) -> bool:
        parsed = urlparse(url)
        hostname = parsed.hostname
        if hostname is None:
            return False
        normalized = hostname.rstrip(".").lower()
        if normalized == "localhost":
            return True
        try:
            return ipaddress.ip_address(normalized).is_loopback
        except ValueError:
            return False

    def _validate_config(self, *, local_only: bool) -> None:
        self._validate_http_url(self._config.endpoint)
        if local_only and not self._is_loopback_url(self._config.endpoint):
            raise SpeechConfigurationError("Local HTTP speech endpoint must use a loopback address")
        method = self._config.method.upper()
        if method not in _ALLOWED_METHODS:
            raise SpeechConfigurationError("HTTP speech method must be POST or PUT")
        if self._config.timeout_seconds <= 0 or self._config.timeout_seconds > 300:
            raise SpeechConfigurationError("HTTP speech timeout must be between 0 and 300 seconds")
        if self._config.max_response_bytes <= 0:
            raise SpeechConfigurationError("HTTP speech maximum response size must be positive")
        for source_field, vendor_field in self._config.field_mappings.items():
            if source_field not in _ALLOWED_REQUEST_FIELDS:
                raise SpeechConfigurationError(
                    f"Unsupported request field mapping: {source_field}"
                )
            if not _VENDOR_FIELD_PATTERN.fullmatch(vendor_field):
                raise SpeechConfigurationError(
                    f"Invalid vendor field mapping: {vendor_field}"
                )
        if self._config.response_mode in {
            HttpSpeechResponseMode.BASE64,
            HttpSpeechResponseMode.URL,
        } and not self._config.response_field:
            raise SpeechConfigurationError(
                "HTTP speech response_field is required for base64 and URL response modes"
            )

    def _build_payload(self, request: SpeechSynthesisRequest) -> dict[str, Any]:
        filtered = filter_supported_controls(request, self.capabilities)
        payload: dict[str, Any] = {}
        for source_field, vendor_field in self._config.field_mappings.items():
            value = getattr(filtered, source_field)
            if value is not None:
                payload[vendor_field] = value
        return payload

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        status = response.status_code
        if 200 <= status < 300:
            return
        message = f"HTTP speech provider returned status {status}"
        if status in (401, 403):
            raise SpeechAuthenticationError(message)
        if status == 429:
            raise SpeechRateLimitError(message)
        raise SpeechRequestError(message)

    async def _read_bounded(self, response: httpx.Response) -> bytes:
        content_length = response.headers.get("content-length")
        if content_length is not None:
            try:
                declared_size = int(content_length)
            except ValueError:
                declared_size = 0
            if declared_size > self._config.max_response_bytes:
                raise SpeechRequestError("HTTP speech response exceeds maximum response size")

        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > self._config.max_response_bytes:
                raise SpeechRequestError("HTTP speech response exceeds maximum response size")
            chunks.append(chunk)
        return b"".join(chunks)

    @staticmethod
    def _extract_response_field(payload: Any, field_path: str) -> Any:
        current = payload
        for part in field_path.split("."):
            if not isinstance(current, dict) or part not in current:
                raise SpeechRequestError(
                    f"HTTP speech response is missing configured field: {field_path}"
                )
            current = current[part]
        return current

    def _validate_audio_url(self, url: str) -> None:
        try:
            self._validate_http_url(url)
        except SpeechConfigurationError as exc:
            raise SpeechRequestError("HTTP speech response contains unsafe audio URL") from exc

    async def _request_bounded(
        self,
        client: httpx.AsyncClient,
        *,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        json_payload: dict[str, Any] | None = None,
    ) -> tuple[httpx.Response, bytes]:
        try:
            async with client.stream(
                method,
                url,
                headers=headers,
                json=json_payload,
                timeout=self._config.timeout_seconds,
                follow_redirects=False,
            ) as response:
                self._raise_for_status(response)
                content = await self._read_bounded(response)
                return response, content
        except httpx.RequestError as exc:
            raise SpeechRequestError(str(exc)) from exc

    async def _synthesize_with_client(
        self,
        client: httpx.AsyncClient,
        request: SpeechSynthesisRequest,
    ) -> SpeechSynthesisResult:
        _, response_bytes = await self._request_bounded(
            client,
            method=self._config.method.upper(),
            url=self._config.endpoint,
            headers=dict(self._config.headers),
            json_payload=self._build_payload(request),
        )

        if self._config.response_mode is HttpSpeechResponseMode.BYTES:
            audio_bytes = response_bytes
        else:
            try:
                response_payload: Any = json.loads(response_bytes.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise SpeechRequestError("HTTP speech provider returned invalid JSON") from exc
            response_field = self._config.response_field
            if response_field is None:
                raise SpeechRequestError("HTTP speech response field is not configured")
            value = self._extract_response_field(response_payload, response_field)

            if self._config.response_mode is HttpSpeechResponseMode.BASE64:
                if not isinstance(value, str):
                    raise SpeechRequestError("HTTP speech base64 field must be a string")
                try:
                    audio_bytes = base64.b64decode(value, validate=True)
                except (binascii.Error, ValueError) as exc:
                    raise SpeechRequestError("HTTP speech response contains invalid base64") from exc
                if len(audio_bytes) > self._config.max_response_bytes:
                    raise SpeechRequestError(
                        "HTTP speech response exceeds maximum response size"
                    )
            else:
                if not isinstance(value, str):
                    raise SpeechRequestError("HTTP speech audio URL field must be a string")
                self._validate_audio_url(value)
                _, audio_bytes = await self._request_bounded(
                    client,
                    method="GET",
                    url=value,
                    headers=None,
                    json_payload=None,
                )

        if not audio_bytes:
            raise SpeechRequestError("HTTP speech provider returned empty audio")

        return SpeechSynthesisResult(
            provider=self.name,
            model=self.model,
            audio_bytes=audio_bytes,
            output_format=self._config.output_format,
            sample_rate=self._config.sample_rate,
            duration_ms=None,
            raw_payload={
                "response_mode": self._config.response_mode.value,
            },
        )

    async def synthesize(self, request: SpeechSynthesisRequest) -> SpeechSynthesisResult:
        if self._client is not None:
            return await self._synthesize_with_client(self._client, request)
        async with httpx.AsyncClient() as client:
            return await self._synthesize_with_client(client, request)


class LocalHttpSpeechProvider(GenericHttpSpeechProvider):
    def __init__(
        self,
        *,
        config: HttpSpeechProviderConfig,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config
        self._client = client
        self._validate_config(local_only=True)

    def _validate_audio_url(self, url: str) -> None:
        super()._validate_audio_url(url)
        if not self._is_loopback_url(url):
            raise SpeechRequestError("Local HTTP speech audio URL must remain on loopback")

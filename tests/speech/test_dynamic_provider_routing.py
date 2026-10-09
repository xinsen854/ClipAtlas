from pathlib import Path
from uuid import uuid4

import pytest

from clipatlas.speech.contracts import SpeechProviderCapabilities
from clipatlas.speech.models import (
    SpeechProfile,
    SpeechSynthesisRequest,
    SpeechSynthesisResult,
)
from clipatlas.speech.registry import SpeechProviderRegistry
from clipatlas.speech.service import NarrationService
from clipatlas.speech.store import NarrationStore


class RecordingProvider:
    capabilities = SpeechProviderCapabilities()

    def __init__(self, name: str, model: str) -> None:
        self._name = name
        self._model = model
        self.calls: list[str] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def model(self) -> str:
        return self._model

    async def list_voices(self) -> list[object]:
        return []

    async def synthesize(self, request: SpeechSynthesisRequest) -> SpeechSynthesisResult:
        self.calls.append(request.text)
        return SpeechSynthesisResult(
            provider=self.name,
            model=self.model,
            audio_bytes=request.text.encode(),
            output_format="wav",
            sample_rate=48_000,
        )


class FixedAudioNormalizer:
    def __init__(self) -> None:
        self._durations: dict[Path, int] = {}

    async def normalize(
        self,
        source: Path,
        destination: Path,
        sample_rate: int = 48_000,
    ) -> Path:
        assert sample_rate == 48_000
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
        self._durations[destination] = 1000
        return destination

    async def probe_duration_ms(self, source: Path) -> int:
        return self._durations[source]

    async def concat(self, inputs: list[Path], destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"".join(path.read_bytes() for path in inputs))
        self._durations[destination] = sum(self._durations[path] for path in inputs)
        return destination


@pytest.mark.asyncio
async def test_narration_service_routes_each_profile_to_its_registered_provider(
    tmp_path: Path,
) -> None:
    dashscope = RecordingProvider("dashscope", "cosyvoice-v3.5-flash")
    local = RecordingProvider("local-http", "local-cosyvoice")
    registry = SpeechProviderRegistry()
    registry.register(dashscope)
    registry.register(local)
    store = NarrationStore(tmp_path / "speech.sqlite3")
    service = NarrationService(
        registry=registry,
        store=store,
        audio_normalizer=FixedAudioNormalizer(),
        narration_root=tmp_path / "narration",
    )
    project_id = uuid4()
    dashscope_profile = SpeechProfile(
        project_id=project_id,
        provider="dashscope",
        model="cosyvoice-v3.5-flash",
        voice_id="custom-dashscope-voice",
        locked=True,
    )
    local_profile = SpeechProfile(
        project_id=project_id,
        provider="local-http",
        model="local-cosyvoice",
        voice_id="local-voice",
        locked=True,
    )

    first = await service.create_tts_track(project_id, "云端旁白", dashscope_profile)
    second = await service.create_tts_track(project_id, "本地旁白", local_profile)

    assert dashscope.calls == ["云端旁白"]
    assert local.calls == ["本地旁白"]
    assert (first.provider, first.model) == ("dashscope", "cosyvoice-v3.5-flash")
    assert (second.provider, second.model) == ("local-http", "local-cosyvoice")

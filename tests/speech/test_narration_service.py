from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from clipatlas.speech.contracts import SpeechProviderCapabilities
from clipatlas.speech.errors import SpeechRequestError
from clipatlas.speech.models import (
    NarrationSourceMode,
    ProviderWordTiming,
    SpeechProfile,
    SpeechSynthesisRequest,
    SpeechSynthesisResult,
    TimingQuality,
)
from clipatlas.speech.service import NarrationService, split_narration_units
from clipatlas.speech.store import NarrationStore


class RecordingSpeechProvider:
    name = "recording"
    model = "recording-v1"
    capabilities = SpeechProviderCapabilities(word_timestamps=True)

    def __init__(self, *, fail_text_once: str | None = None) -> None:
        self.calls: list[str] = []
        self._fail_text_once = fail_text_once
        self._failed = False

    async def list_voices(self) -> list[object]:
        return []

    async def synthesize(self, request: SpeechSynthesisRequest) -> SpeechSynthesisResult:
        self.calls.append(request.text)
        if request.text == self._fail_text_once and not self._failed:
            self._failed = True
            raise SpeechRequestError("temporary synthesis failure")
        timings = []
        if request.text == "第一句":
            timings = [
                ProviderWordTiming(
                    sequence=0,
                    word="第一句",
                    start_ms=100,
                    end_ms=500,
                    confidence=0.99,
                )
            ]
        return SpeechSynthesisResult(
            provider=self.name,
            model=self.model,
            audio_bytes=request.text.encode(),
            output_format="wav",
            sample_rate=48_000,
            word_timings=timings,
        )


class DeterministicAudioNormalizer:
    def __init__(self, durations_by_text: dict[str, int]) -> None:
        self._durations_by_text = durations_by_text
        self._duration_by_path: dict[Path, int] = {}

    def _duration_for(self, source: Path) -> int:
        if source in self._duration_by_path:
            return self._duration_by_path[source]
        return self._durations_by_text[source.read_bytes().decode()]

    async def normalize(
        self,
        source: Path,
        destination: Path,
        sample_rate: int = 48_000,
    ) -> Path:
        assert source.is_file()
        assert sample_rate == 48_000
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
        self._duration_by_path[destination] = self._duration_for(source)
        return destination

    async def probe_duration_ms(self, source: Path) -> int:
        return self._duration_for(source)

    async def concat(self, inputs: list[Path], destination: Path) -> Path:
        assert inputs
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"".join(path.read_bytes() for path in inputs))
        self._duration_by_path[destination] = sum(self._duration_for(path) for path in inputs)
        return destination


def _profile(project_id: UUID) -> SpeechProfile:
    return SpeechProfile(
        project_id=project_id,
        provider="recording",
        model="recording-v1",
        voice_id="voice-1",
        speed=1.0,
        pitch=1.0,
        volume=1.0,
        locked=True,
    )


def _script_hash(script: str) -> str:
    return sha256(script.encode()).hexdigest()


def _durations() -> dict[str, int]:
    return {"第一句": 1200, "第二句": 800, "第三句": 1500, "同一句": 1000}


def test_split_narration_units_is_deterministic_and_ignores_blank_lines() -> None:
    assert split_narration_units("第一句。\n\n第二句！\n第三句？") == [
        "第一句。",
        "第二句！",
        "第三句？",
    ]


@pytest.mark.asyncio
async def test_create_tts_track_uses_measured_unit_durations_as_canonical_timeline(
    tmp_path: Path,
) -> None:
    project_id = uuid4()
    store = NarrationStore(tmp_path / "speech.sqlite3")
    provider = RecordingSpeechProvider()
    normalizer = DeterministicAudioNormalizer(_durations())
    service = NarrationService(
        provider=provider,
        store=store,
        audio_normalizer=normalizer,
        narration_root=tmp_path / "narration",
    )
    profile = _profile(project_id)

    track = await service.create_tts_track(
        project_id,
        "第一句\n第二句\n第三句",
        profile,
    )

    units = store.list_units(track.id)
    assert [(unit.start_ms, unit.end_ms) for unit in units] == [
        (0, 1200),
        (1200, 2000),
        (2000, 3500),
    ]
    assert track.source_mode == NarrationSourceMode.TTS
    assert track.duration_ms == 3500
    assert track.timing_quality == TimingQuality.UNIT_EXACT
    assert track.audio_uri is not None
    assert store.get_active_track(project_id) == track
    word_timings = store.list_word_timings(track.id)
    assert [(item.start_ms, item.end_ms) for item in word_timings] == [(100, 500)]


@pytest.mark.asyncio
async def test_retry_reuses_incomplete_track_and_skips_completed_units_across_requests(
    tmp_path: Path,
) -> None:
    project_id = uuid4()
    db_path = tmp_path / "speech.sqlite3"
    script = "第一句\n第二句\n第三句"
    profile = _profile(project_id)
    first_provider = RecordingSpeechProvider(fail_text_once="第三句")
    first_service = NarrationService(
        provider=first_provider,
        store=NarrationStore(db_path),
        audio_normalizer=DeterministicAudioNormalizer(_durations()),
        narration_root=tmp_path / "narration",
    )

    with pytest.raises(SpeechRequestError, match="temporary synthesis failure"):
        await first_service.create_tts_track(project_id, script, profile)

    resumed_store = NarrationStore(db_path)
    resumable = resumed_store.find_resumable_tts_track(
        project_id,
        _script_hash(script),
        profile.id,
    )
    assert resumable is not None
    assert [(unit.sequence, unit.text) for unit in resumed_store.list_units(resumable.id)] == [
        (0, "第一句"),
        (1, "第二句"),
    ]

    second_provider = RecordingSpeechProvider()
    second_service = NarrationService(
        provider=second_provider,
        store=resumed_store,
        audio_normalizer=DeterministicAudioNormalizer(_durations()),
        narration_root=tmp_path / "narration",
    )
    track = await second_service.create_tts_track(project_id, script, profile)

    assert track.id == resumable.id
    assert first_provider.calls == ["第一句", "第二句", "第三句"]
    assert second_provider.calls == ["第三句"]
    assert [(unit.start_ms, unit.end_ms) for unit in resumed_store.list_units(track.id)] == [
        (0, 1200),
        (1200, 2000),
        (2000, 3500),
    ]


@pytest.mark.asyncio
async def test_successful_regeneration_creates_new_revision_without_overwriting_old_track(
    tmp_path: Path,
) -> None:
    project_id = uuid4()
    store = NarrationStore(tmp_path / "speech.sqlite3")
    provider = RecordingSpeechProvider()
    profile = _profile(project_id)

    first = await NarrationService(
        provider=provider,
        store=store,
        audio_normalizer=DeterministicAudioNormalizer(_durations()),
        narration_root=tmp_path / "narration",
    ).create_tts_track(project_id, "同一句", profile)
    second_normalizer = DeterministicAudioNormalizer({**_durations(), "同一句": 1100})
    second = await NarrationService(
        provider=provider,
        store=store,
        audio_normalizer=second_normalizer,
        narration_root=tmp_path / "narration",
    ).create_tts_track(project_id, "同一句", profile)

    assert first.id != second.id
    assert first.revision == 1
    assert second.revision == 2
    assert store.get_track(first.id) == first
    assert store.get_track(second.id) == second
    assert store.get_active_track(project_id) == second

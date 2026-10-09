from pathlib import Path
from uuid import uuid4

import pytest

from clipatlas.speech.alignment import (
    AlignmentResult,
    AlignmentUnitTiming,
    AlignmentWordTiming,
)
from clipatlas.speech.errors import SpeechAudioValidationError
from clipatlas.speech.importer import ImportedNarrationService
from clipatlas.speech.models import NarrationSourceMode, TimingQuality
from clipatlas.speech.store import NarrationStore


class ImportedAudioNormalizer:
    def __init__(self, duration_ms: int) -> None:
        self.duration_ms = duration_ms

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
        return destination

    async def probe_duration_ms(self, source: Path) -> int:
        assert source.is_file()
        return self.duration_ms


class StaticAligner:
    def __init__(self, result: AlignmentResult | None) -> None:
        self.result = result
        self.calls: list[tuple[Path, list[str]]] = []

    async def align(self, audio_path: Path, script_units: list[str]) -> AlignmentResult | None:
        self.calls.append((audio_path, script_units))
        return self.result


@pytest.mark.asyncio
async def test_import_without_aligner_uses_real_track_duration_and_does_not_fake_unit_times(
    tmp_path: Path,
) -> None:
    source = tmp_path / "voice.mp3"
    original = b"original-human-narration"
    source.write_bytes(original)
    project_id = uuid4()
    store = NarrationStore(tmp_path / "speech.sqlite3")
    service = ImportedNarrationService(
        store=store,
        audio_normalizer=ImportedAudioNormalizer(4321),
        narration_root=tmp_path / "narration",
    )

    track = await service.import_track(project_id, source, "第一句\n第二句")

    assert source.read_bytes() == original
    assert track.source_mode == NarrationSourceMode.IMPORTED
    assert track.duration_ms == 4321
    assert track.timing_quality == TimingQuality.TRACK_ONLY
    assert track.audio_uri is not None
    assert Path(track.audio_uri.removeprefix("file://")).name == "track.wav"
    units = store.list_units(track.id)
    assert [unit.text for unit in units] == ["第一句", "第二句"]
    assert all(unit.start_ms is None and unit.end_ms is None for unit in units)
    assert store.list_word_timings(track.id) == []
    assert store.get_active_track(project_id) == track


@pytest.mark.asyncio
async def test_import_with_valid_alignment_persists_aligned_units_and_words(
    tmp_path: Path,
) -> None:
    source = tmp_path / "voice.wav"
    source.write_bytes(b"human")
    project_id = uuid4()
    store = NarrationStore(tmp_path / "speech.sqlite3")
    aligner = StaticAligner(
        AlignmentResult(
            units=[
                AlignmentUnitTiming(sequence=0, start_ms=0, end_ms=1200),
                AlignmentUnitTiming(sequence=1, start_ms=1300, end_ms=3000),
            ],
            words=[
                AlignmentWordTiming(
                    unit_sequence=1,
                    sequence=0,
                    word="第二句",
                    start_ms=1400,
                    end_ms=1900,
                    confidence=0.95,
                )
            ],
        )
    )
    service = ImportedNarrationService(
        store=store,
        audio_normalizer=ImportedAudioNormalizer(3500),
        narration_root=tmp_path / "narration",
    )

    track = await service.import_track(
        project_id,
        source,
        "第一句\n第二句",
        aligner=aligner,
    )

    assert track.timing_quality == TimingQuality.ALIGNED
    assert [(unit.start_ms, unit.end_ms) for unit in store.list_units(track.id)] == [
        (0, 1200),
        (1300, 3000),
    ]
    words = store.list_word_timings(track.id)
    assert [(word.word, word.start_ms, word.end_ms) for word in words] == [
        ("第二句", 1400, 1900)
    ]
    assert aligner.calls[0][1] == ["第一句", "第二句"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "alignment",
    [
        AlignmentResult(
            units=[
                AlignmentUnitTiming(sequence=0, start_ms=0, end_ms=1500),
                AlignmentUnitTiming(sequence=1, start_ms=1400, end_ms=2500),
            ]
        ),
        AlignmentResult(
            units=[
                AlignmentUnitTiming(sequence=0, start_ms=0, end_ms=1200),
                AlignmentUnitTiming(sequence=1, start_ms=1300, end_ms=4001),
            ]
        ),
        AlignmentResult(
            units=[AlignmentUnitTiming(sequence=0, start_ms=0, end_ms=1200)]
        ),
    ],
)
async def test_invalid_alignment_is_rejected_without_activating_track(
    tmp_path: Path,
    alignment: AlignmentResult,
) -> None:
    source = tmp_path / "voice.wav"
    source.write_bytes(b"human")
    project_id = uuid4()
    store = NarrationStore(tmp_path / "speech.sqlite3")
    service = ImportedNarrationService(
        store=store,
        audio_normalizer=ImportedAudioNormalizer(3500),
        narration_root=tmp_path / "narration",
    )

    with pytest.raises(SpeechAudioValidationError):
        await service.import_track(
            project_id,
            source,
            "第一句\n第二句",
            aligner=StaticAligner(alignment),
        )

    assert store.get_active_track(project_id) is None


@pytest.mark.asyncio
async def test_aligner_returning_none_falls_back_to_track_only_without_fake_timestamps(
    tmp_path: Path,
) -> None:
    source = tmp_path / "voice.wav"
    source.write_bytes(b"human")
    project_id = uuid4()
    store = NarrationStore(tmp_path / "speech.sqlite3")
    service = ImportedNarrationService(
        store=store,
        audio_normalizer=ImportedAudioNormalizer(2500),
        narration_root=tmp_path / "narration",
    )

    track = await service.import_track(
        project_id,
        source,
        "只有一句",
        aligner=StaticAligner(None),
    )

    assert track.timing_quality == TimingQuality.TRACK_ONLY
    assert store.list_units(track.id)[0].start_ms is None


@pytest.mark.asyncio
async def test_reimport_creates_new_revision_and_preserves_old_track(tmp_path: Path) -> None:
    source = tmp_path / "voice.wav"
    source.write_bytes(b"human")
    project_id = uuid4()
    store = NarrationStore(tmp_path / "speech.sqlite3")
    service = ImportedNarrationService(
        store=store,
        audio_normalizer=ImportedAudioNormalizer(2000),
        narration_root=tmp_path / "narration",
    )

    first = await service.import_track(project_id, source, "一句")
    second = await service.import_track(project_id, source, "一句")

    assert first.id != second.id
    assert first.revision == 1
    assert second.revision == 2
    assert store.get_track(first.id) == first
    assert store.get_track(second.id) == second
    assert store.get_active_track(project_id) == second

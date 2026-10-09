import json
from hashlib import sha256
from uuid import uuid4

import pytest

from clipatlas.asr.models import ASRSentence, ASRWord
from clipatlas.speech.errors import SpeechAudioValidationError
from clipatlas.speech.models import NarrationTrack, NarrationUnit
from clipatlas.speech.narration_alignment import (
    NarrationAlignmentService,
    align_script,
    align_source_units,
)
from clipatlas.speech.store import NarrationStore


def transcript(text, start=200):
    words = [ASRWord(text=c, start_ms=start + i * 200, end_ms=start + (i + 1) * 200)
             for i, c in enumerate(text)]
    return [ASRSentence(text=text, start_ms=start, end_ms=words[-1].end_ms, words=words)]


def test_alignment_uses_asr_times_and_reports_unspoken_heading():
    first = "这辆越野车正在山间的碎石路上平稳行驶"
    second = "座舱里面的皮质座椅正在展示舒适体验"
    texts, result, notes = align_script(["未朗读的文章标题", first + "。", second + "。"],
                                       transcript(first + second), 10000)
    assert texts == [first + "。", second + "。"]
    assert result.units[0].start_ms == 200
    assert result.units[0].end_ms == 200 + len(first) * 200
    assert result.units[1].start_ms == result.units[0].end_ms
    assert "未在旁白中读出" in notes[0]


def test_mismatched_audio_and_missing_word_times_are_rejected():
    with pytest.raises(SpeechAudioValidationError):
        align_script(["车内座椅展示"], transcript("今天讲解如何烘焙面包"), 10000)
    with pytest.raises(SpeechAudioValidationError, match="词级时间"):
        align_script(["车辆行驶"], [ASRSentence(start_ms=0, end_ms=3000, text="车辆行驶")], 3000)


def test_source_alignment_maps_character_offsets_to_multichar_asr_words():
    words = [
        ASRWord(text="泰钽700", start_ms=100, end_ms=600),
        ASRWord(text="在", start_ms=600, end_ms=700),
        ASRWord(text="山路", start_ms=700, end_ms=1000),
        ASRWord(text="行驶", start_ms=1000, end_ms=1400),
    ]
    sentences = [ASRSentence(
        text="泰钽700在山路行驶", start_ms=100, end_ms=1400, words=words,
    )]

    result, _ = align_source_units(["泰钽700在山路行驶"], sentences, 1500)

    assert (result.units[0].start_ms, result.units[0].end_ms) == (100, 1400)
    assert result.units[0].confidence == 1.0


@pytest.mark.asyncio
async def test_alignment_snapshot_reuses_observed_audio_and_preserves_original(tmp_path):
    store = NarrationStore(tmp_path / "narration.sqlite3")
    audio = tmp_path / "track.wav"
    audio.write_bytes(b"fixture audio whose ASR is cached")
    text = "车辆在山路上行驶"
    track = NarrationTrack(project_id=uuid4(), source_mode="imported", script_hash="script",
                           audio_uri=audio.as_uri(), duration_ms=3000, timing_quality="track_only")
    store.save_track(track)
    store.save_unit(NarrationUnit(track_id=track.id, sequence=0, text=text, text_hash="unit"))
    store.activate_track(track.project_id, track.id)
    class NoCloud:
        model = "fixture"
        async def transcribe(self, path):
            raise AssertionError("A repeated generation must reuse the audio transcript")
    root = tmp_path / str(track.project_id) / str(track.id) / "alignment"
    root.mkdir(parents=True)
    (root / f"fixture-{sha256(audio.read_bytes()).hexdigest()}.json").write_text(
        json.dumps([s.model_dump() for s in transcript(text)], ensure_ascii=False), encoding="utf-8")
    service = NarrationAlignmentService(store=store, provider=NoCloud(), root=tmp_path)
    result = await service.ensure_aligned(track)
    assert result.timing_quality == "aligned" and result.alignment_source_id == track.id
    aligned_units = store.list_units(result.id)
    assert [unit.text for unit in aligned_units] == [text]
    assert result.alignment_maps[0].source_quote == text
    assert store.get_track(track.id) == track
    assert store.get_active_track(track.project_id).id == track.id
    assert (await service.ensure_aligned(track)).id == result.id
    assert len(store.list_tracks(track.project_id)) == 2

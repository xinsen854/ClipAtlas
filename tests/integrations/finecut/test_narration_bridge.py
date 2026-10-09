from uuid import uuid4

from clipatlas.integrations.finecut.narration_bridge import narration_reference
from clipatlas.roughcut.models import ScriptBeat
from clipatlas.speech.models import NarrationSourceMode, NarrationTrack, TimingQuality


def _beat(track_id, *, sequence: int, start_ms: int, end_ms: int, text: str) -> ScriptBeat:
    return ScriptBeat(
        project_id=uuid4(),
        narration_track_id=track_id,
        sequence=sequence,
        text=text,
        timeline_start_ms=start_ms,
        timeline_end_ms=end_ms,
        target_duration_ms=end_ms - start_ms,
        query_text=text,
    )


def test_narration_bridge_copies_track_and_beat_ranges_only() -> None:
    project_id = uuid4()
    track = NarrationTrack(
        project_id=project_id,
        source_mode=NarrationSourceMode.TTS,
        script_hash="hash",
        audio_uri="D:/audio/narration.wav",
        duration_ms=6_000,
        timing_quality=TimingQuality.WORD_EXACT,
        revision=3,
        provider="provider-that-must-not-leak",
        model="model-that-must-not-leak",
    )
    beats = [
        _beat(track.id, sequence=0, start_ms=0, end_ms=2_500, text="第一句"),
        _beat(track.id, sequence=1, start_ms=2_500, end_ms=6_000, text="第二句"),
    ]

    result = narration_reference(track, beats)

    assert result.track_id == track.id
    assert result.revision == 3
    assert result.audio_uri == "D:/audio/narration.wav"
    assert result.duration_ms == 6_000
    assert [segment.id for segment in result.segments] == [beats[0].id, beats[1].id]
    assert [segment.text for segment in result.segments] == ["第一句", "第二句"]
    assert [(segment.start_ms, segment.end_ms) for segment in result.segments] == [
        (0, 2_500), (2_500, 6_000),
    ]
    assert set(result.model_dump()) == {
        "track_id", "revision", "audio_uri", "duration_ms", "segments",
    }
    assert set(result.segments[0].model_dump()) == {"id", "text", "start_ms", "end_ms"}


def test_narration_bridge_preserves_missing_audio_uri() -> None:
    track = NarrationTrack(
        project_id=uuid4(),
        source_mode=NarrationSourceMode.IMPORTED,
        script_hash="hash",
        audio_uri=None,
        duration_ms=1_000,
        timing_quality=TimingQuality.TRACK_ONLY,
    )
    beat = _beat(track.id, sequence=0, start_ms=0, end_ms=1_000, text="一句")

    result = narration_reference(track, [beat])

    assert result.audio_uri is None


def test_narration_bridge_exposes_visual_only_beats_as_editing_contexts() -> None:
    track = NarrationTrack(
        project_id=uuid4(),
        source_mode=NarrationSourceMode.IMPORTED,
        script_hash="hash",
        audio_uri="D:/audio/original.wav",
        duration_ms=2_000,
        timing_quality=TimingQuality.UNIT_EXACT,
    )
    beat = ScriptBeat(
        project_id=uuid4(),
        narration_track_id=track.id,
        sequence=0,
        kind="visual_only",
        text="",
        timeline_start_ms=0,
        timeline_end_ms=2_000,
        target_duration_ms=2_000,
        query_text="兽人围桌查看地图",
    )

    result = narration_reference(track, [beat], include_visual_only=True)

    assert result.segments[0].id == beat.id
    assert result.segments[0].text == "兽人围桌查看地图"

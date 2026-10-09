from clipatlas.roughcut.models import ScriptBeat
from clipatlas.speech.models import NarrationTrack
from finecut.models import NarrationReference, NarrationSegmentReference


def narration_reference(
    track: NarrationTrack,
    beats: list[ScriptBeat],
    *,
    include_visual_only: bool = False,
) -> NarrationReference:
    return NarrationReference(
        track_id=track.id,
        revision=track.revision,
        audio_uri=track.audio_uri,
        duration_ms=track.duration_ms,
        segments=[
            NarrationSegmentReference(
                id=beat.id,
                text=beat.text.strip() or beat.query_text.strip() or f"镜头 {beat.sequence + 1}",
                start_ms=beat.timeline_start_ms,
                end_ms=beat.timeline_end_ms,
            )
            for beat in beats
            if beat.kind == "narration" or include_visual_only
        ],
    )

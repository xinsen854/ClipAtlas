from uuid import uuid4

from clipatlas.integrations.finecut.candidate_bridge import candidate_list_from_beat
from clipatlas.roughcut.models import ScriptBeat
from finecut.models import Clip


def test_candidate_list_can_contain_candidate_shorter_than_current_timeline_slot() -> None:
    project_id = uuid4()
    track_id = uuid4()
    beat = ScriptBeat(
        project_id=project_id,
        narration_track_id=track_id,
        sequence=0,
        text="需要九秒画面覆盖的当前句",
        timeline_start_ms=0,
        timeline_end_ms=9000,
        target_duration_ms=9000,
        query_text="需要九秒画面覆盖的当前句",
        retrieval_intent={
            "candidate_matrix": [
                {
                    "requirement_id": "req-short",
                    "video_id": str(uuid4()),
                    "start_ms": 1000,
                    "end_ms": 4500,
                    "match_level": "DIRECT",
                    "pollution_level": "clean",
                }
            ]
        },
    )
    current_clip = Clip(
        source_id="current-segment",
        source_path="D:/media/current.mp4",
        timeline_start_ms=0,
        duration_ms=9000,
        source_in_ms=0,
        source_out_ms=9000,
    )

    candidates = candidate_list_from_beat(beat)

    assert len(candidates.items) == 1
    candidate = candidates.items[0]
    assert candidate.display_level == "S"
    assert candidate.source_out_ms - candidate.source_in_ms == 3500
    assert candidate.source_out_ms - candidate.source_in_ms < current_clip.duration_ms

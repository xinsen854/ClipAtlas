from hashlib import sha256
from uuid import uuid4

from clipatlas.director.requirements import parse_script_visual_requirements
from clipatlas.domain.visual_protocol import VideoSequenceWindow, VideoTimelineEvent


def test_requirements_keep_source_ranges_and_split_clauses_without_cut_instruction():
    text = "\u6cf0\u94bd700\u5728\u6c99\u783e\u8def\u9762\u884c\u9a76\uff0c\u968f\u540e\u722c\u4e0a\u9661\u5761\u3002"
    requirements = parse_script_visual_requirements(text)

    assert len(requirements) == 2
    assert [item.source_quote for item in requirements] == [
        text[: text.index("\uff0c") + 1], text[text.index("\uff0c") + 1 :]
    ]
    assert all(item.source_text_hash == sha256(text.encode()).hexdigest() for item in requirements)
    assert requirements[1].temporal_relation == "after"
    assert requirements[1].subject == "\u6cf0\u94bd700"
    assert requirements[1].same_subject_required is True
    assert requirements[1].continuous_action_required is True
    assert requirements[0].origin == "local_fallback"
    assert "碎石路" in requirements[0].related_expressions
    assert requirements[0].must_have == ["泰钽700", "行驶", "沙砾路"]


def test_unknown_continuity_is_not_upgraded_to_confirmed():
    video_id = uuid4()
    event = VideoTimelineEvent(video_id=video_id, start_ms=0, end_ms=1000, action="\u884c\u9a76")
    window = VideoSequenceWindow(
        video_id=video_id,
        start_ms=0,
        end_ms=1000,
        event_ids=[event.id],
        continuity_status="unknown_continuity",
    )
    assert window.continuity_status == "unknown_continuity"

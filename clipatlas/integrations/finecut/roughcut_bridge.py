from clipatlas.roughcut.models import RoughCutPlan
from finecut.models import Clip, TimelineDocument, Track


def timeline_from_roughcut(
    plan: RoughCutPlan,
    *,
    width: int = 1920,
    height: int = 1080,
    fps: float = 30.0,
) -> TimelineDocument:
    video_clips = [
        Clip(
            source_id=str(clip.segment_id),
            source_path=clip.source_uri,
            timeline_start_ms=clip.timeline_in_ms,
            duration_ms=clip.timeline_out_ms - clip.timeline_in_ms,
            source_in_ms=clip.source_in_ms,
            source_out_ms=clip.source_out_ms,
        )
        for clip in plan.clips
    ]
    return TimelineDocument(
        project_id=plan.project_id,
        source_plan_id=plan.id,
        width=width,
        height=height,
        fps=fps,
        duration_ms=plan.total_duration_ms,
        tracks=[Track(kind="video", clips=video_clips)],
    )

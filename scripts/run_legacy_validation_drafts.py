from __future__ import annotations

import asyncio
import json
import os
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4, uuid5

from clipatlas.exports.models import JianyingExportSettings
from clipatlas.speech.store import NarrationStore


PROJECT_ID = UUID("33f11f8c-d29c-4791-9bf7-7bd6c1fd85db")
TRACKS = (
    (
        UUID("06c22419-c161-5fcb-8612-a6c8b912ee55"),
        UUID("6ed128be-f2e5-4c31-be1d-9cc35803bf27"),
        "权威认证首次正名",
    ),
    (
        UUID("14ba7adc-26ae-5234-b916-2c8d7451e904"),
        UUID("4707369a-51d9-419a-8276-cd160b288056"),
        "全程直播背后的高光时刻",
    ),
    (
        UUID("37f60de9-cde6-5408-88d4-dad731446f04"),
        UUID("7aed802f-c9d0-4f37-aafa-e3194493c634"),
        "性能豪华定位连答三题",
    ),
)


def _source_audio(data_root: Path, raw_track_id: UUID) -> Path:
    matches = list(data_root.glob(f"narration/*/{raw_track_id}/track.wav"))
    if len(matches) != 1:
        raise RuntimeError(f"expected one source audio for {raw_track_id}, got {len(matches)}")
    return matches[0]


def _clone_track(
    source: NarrationStore,
    target: NarrationStore,
    data_root: Path,
    aligned_id: UUID,
    raw_id: UUID,
    title: str,
) -> UUID:
    original = source.get_track(aligned_id)
    if original is None:
        raise RuntimeError(f"source narration track missing: {aligned_id}")
    new_id = uuid4()
    audio_dir = Path.cwd() / "data" / "narration" / "validation-v1.0.14" / str(new_id)
    audio_dir.mkdir(parents=True, exist_ok=True)
    audio = audio_dir / "track.wav"
    shutil.copy2(_source_audio(data_root, raw_id), audio)
    clone = original.model_copy(update={
        "id": new_id,
        "project_id": PROJECT_ID,
        "alignment_source_id": None,
        "alignment_notes": [*original.alignment_notes, f"ClipAtlas v1.0.14 验收：{title}"],
        "audio_uri": audio.resolve().as_uri(),
        "rule_pack_revision": None,
        "revision": target.next_track_revision(PROJECT_ID),
    })
    units = []
    unit_map: dict[UUID, UUID] = {}
    for unit in source.list_units(aligned_id):
        unit_id = uuid5(new_id, str(unit.id))
        unit_map[unit.id] = unit_id
        units.append(unit.model_copy(update={
            "id": unit_id,
            "track_id": new_id,
            "audio_uri": audio.resolve().as_uri(),
        }))
    target.save_track_snapshot(clone, units)
    timings = []
    for timing in source.list_word_timings(aligned_id):
        mapped = unit_map.get(timing.unit_id)
        if mapped is not None:
            timings.append(timing.model_copy(update={"unit_id": mapped}))
    if timings:
        target.save_word_timings(timings)
    return new_id


async def main() -> None:
    source_data = Path(os.environ["CLIPATLAS_VALIDATION_SOURCE_DATA"]).resolve()
    from clipatlas.main import app

    if app.state.rough_cut_planner is None:
        raise RuntimeError("rough-cut planner is unavailable")
    if app.state.jianying_backend is None:
        raise RuntimeError("Jianying backend is unavailable")

    source_store = NarrationStore(source_data / "narration" / "narration.sqlite3")
    target_store = app.state.narration_store
    with app.state.library_store._connect() as connection:
        root = connection.execute(
            "SELECT id FROM library_roots WHERE project_id=? "
            "ORDER BY created_at DESC LIMIT 1", (str(PROJECT_ID),),
        ).fetchone()
        if root is None:
            raise RuntimeError("0909 validation material root not found")
        rows = connection.execute(
            "SELECT video_id FROM library_items WHERE root_id=? "
            "AND status='COMPLETED' AND video_id IS NOT NULL",
            (root["id"],),
        ).fetchall()
    video_ids = [UUID(row["video_id"]) for row in rows]
    if len(video_ids) != 11:
        raise RuntimeError(f"expected 11 validation videos, got {len(video_ids)}")

    draft_root = Path(os.environ["CLIPATLAS_JIANYING_DRAFT_ROOT"]).resolve()
    run_stamp = datetime.now().strftime("%Y%m%d-%H%M")
    reports = []
    batch_usage: dict[str, list[tuple[int, int, int]]] = {}
    for index, (aligned_id, raw_id, title) in enumerate(TRACKS, 1):
        track_id = _clone_track(
            source_store, target_store, source_data, aligned_id, raw_id, title,
        )
        plan = await app.state.rough_cut_planner.create_plan(
            PROJECT_ID,
            narration_track_id=track_id,
            video_ids=video_ids,
            activate=False,
            batch_usage=batch_usage,
            batch_index=index - 1,
        )
        for clip in plan.clips:
            batch_usage.setdefault(str(clip.video_id), []).append(
                (clip.source_in_ms, clip.source_out_ms, index - 1)
            )
        draft_name = f"ClipAtlas-v1.0.14-验收{index}-{title}-{run_stamp}"
        artifact = app.state.export_service.export_jianying(
            plan.id,
            draft_name=draft_name,
            settings=JianyingExportSettings(
                draft_root=draft_root,
                width=1920,
                height=1080,
                cover_title=title,
            ),
        )
        duration_by_level: Counter[str] = Counter()
        duration_by_video: Counter[str] = Counter()
        for clip in plan.clips:
            duration = clip.timeline_out_ms - clip.timeline_in_ms
            duration_by_level[clip.schedule_level] += duration
            duration_by_video[str(clip.video_id)] += duration
        exact_ms = duration_by_level["exact"]
        contextual_ms = exact_ms + duration_by_level["related"]
        reports.append({
            "title": title,
            "track_id": str(track_id),
            "plan_id": str(plan.id),
            "draft_name": draft_name,
            "draft_path": str(artifact.output_path),
            "duration_ms": plan.total_duration_ms,
            "beats": len(plan.beats),
            "clips": len(plan.clips),
            "videos": len(duration_by_video),
            "levels": dict(duration_by_level),
            "exact_duration_rate": round(exact_ms / plan.total_duration_ms, 4),
            "contextual_duration_rate": round(contextual_ms / plan.total_duration_ms, 4),
            "max_video_share": round(max(duration_by_video.values()) / plan.total_duration_ms, 4),
            "warnings": plan.warnings,
        })
        print(json.dumps(reports[-1], ensure_ascii=False), flush=True)

    report_path = Path.home() / "Desktop" / f"ClipAtlas-v1.0.14-三条草稿验收-{run_stamp}.json"
    report_path.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"REPORT={report_path}")


if __name__ == "__main__":
    asyncio.run(main())

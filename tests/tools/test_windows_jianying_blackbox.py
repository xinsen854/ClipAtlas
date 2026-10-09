import json
from pathlib import Path

from clipatlas.tools.windows_jianying_blackbox import create_blackbox_fixture


def test_blackbox_helper_generates_isolated_otio_and_jianying_draft(tmp_path: Path) -> None:
    draft_root = tmp_path / "JianyingPro Drafts"
    draft_root.mkdir()
    work_root = tmp_path / "work"

    result = create_blackbox_fixture(
        draft_root=draft_root,
        work_root=work_root,
        draft_name="ClipAtlas-Win-Blackbox",
        prefer_ffmpeg=False,
    )

    assert result.real_video is False
    assert result.plan_id
    assert result.otio_path.is_file()
    assert result.draft_path == (draft_root / "ClipAtlas-Win-Blackbox").resolve()
    assert result.draft_content_path.is_file()
    assert result.total_duration_ms == 5000

    payload = json.loads(result.draft_content_path.read_text(encoding="utf-8"))
    tracks = {track["name"]: track for track in payload["tracks"]}
    assert set(tracks) == {"main_video", "narration"}
    assert tracks["narration"]["segments"][0]["target_timerange"] == {
        "start": 0,
        "duration": 5_000_000,
    }

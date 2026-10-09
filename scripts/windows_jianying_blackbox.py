from __future__ import annotations

import argparse
from pathlib import Path

from clipatlas.tools.windows_jianying_blackbox import create_blackbox_fixture


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create an isolated ClipAtlas OTIO/Jianying black-box fixture."
    )
    parser.add_argument("draft_root", type=Path, help="Real Jianying draft root directory")
    parser.add_argument(
        "--work-root",
        type=Path,
        default=Path("data/windows-blackbox"),
        help="Isolated fixture workspace (default: data/windows-blackbox)",
    )
    parser.add_argument(
        "--draft-name",
        default="ClipAtlas-Win-Blackbox",
        help="Draft name shown by Jianying",
    )
    parser.add_argument(
        "--no-ffmpeg",
        action="store_true",
        help="Use a PNG fixture even if FFmpeg is available",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    result = create_blackbox_fixture(
        draft_root=args.draft_root,
        work_root=args.work_root,
        draft_name=args.draft_name,
        prefer_ffmpeg=not args.no_ffmpeg,
    )

    print()
    print("========== ClipAtlas Windows 黑盒样本完成 ==========")
    print(f"真实 MP4: {result.real_video}")
    print(f"测试素材: {result.source_path}")
    print(f"旁白音频: {result.narration_path}")
    print(f"PLAN_ID: {result.plan_id}")
    print(f"OTIO: {result.otio_path}")
    print(f"剪映草稿: {result.draft_path}")
    print(f"总时长: {result.total_duration_ms} ms")
    print(f"draft_content.json: {result.draft_content_path.is_file()}")
    print("===================================================")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

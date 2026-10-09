from fractions import Fraction
from importlib import import_module
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path, PureWindowsPath
from re import compile as _compile_re
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname
from uuid import UUID

import opentimelineio as otio  # type: ignore[import-untyped]

from clipatlas.exports.errors import (
    JianyingConfigurationError,
    JianyingDependencyError,
    JianyingMediaError,
    JianyingTimeError,
    JianyingWriteError,
)
from clipatlas.exports.models import (
    JianyingDraftArtifact,
    JianyingExportSettings,
    JianyingMode,
    validate_draft_name,
)

_MATERIAL_DURATION_RE = _compile_re(r"素材时长\((\d+)\)")

# Jianying's UI position field is 3100x the draft file's transform unit
# (measured: writing transform_y=-879.0 renders as UI position Y=-2724900).
# To show the desired UI value, divide it by this scale.
_JIANYING_UI_POSITION_SCALE = 3100.0

# 片头标题卡规则：标题不带标点（中文标点全去、英文句子标点去），
# 但保留小数点与连字符（L2.5、44个月-12个月 这类型号不被拆开）；
# 按字数自动分档字号；9:16（竖屏）默认背景模糊。
_TITLE_PUNCT = _compile_re(
    r"[，。！？、；：\u201c\u201d\u2018\u2019（）《》〈〉【】…—·–—,?!;:'\""
    r"\u0028\u0029\u005b\u005d{}<>~`|/\\_@#$%^&*+=]"
)
_TITLE_SPACE = _compile_re(r"\s+")
_TITLE_LEADING_MS = 4_000


def clean_title_text(title: str) -> str:
    """片头标题规则：去掉全部标点符号，压缩空白，保留中英文与数字。

    示例：“L2.5、L2.9？强制国标一出，全作废！” -> “L2.5 L2.9 强制国标一出 全作废”。
    """
    text = _TITLE_PUNCT.sub(" ", title or "")
    return _TITLE_SPACE.sub(" ", text).strip()


def split_title_lines(title: str, max_single: int = 12) -> list[str]:
    """把标题按字数拆成最多两行；短标题保持单行。

    长标题从中间断开，优先在空格处断行，避免切断英文/数字词。
    """
    total = len(title)
    if total <= max_single:
        return [title]
    half = (total + 1) // 2
    for cut in (half, half - 1, half + 1, half - 2, half + 2):
        if 0 < cut < total and title[cut] == " ":
            return [title[:cut].rstrip(), title[cut:].lstrip()]
    return [title[:half], title[half:]]


def title_layout(title: str, *, width: int, height: int) -> dict[str, object]:
    """按画幅与总字数决定主/副标题字号与 UI 位置（Jianying UI 坐标）。

    9:16 竖屏默认两行档位；16:9 横屏字号整体更小。
    返回：lines, main_size, sub_size, main_y, sub_y。
    """
    lines = split_title_lines(clean_title_text(title))
    vertical = height > width
    total = len("".join(lines))
    if vertical:
        if total <= 8:
            main_size, sub_size, main_y, sub_y = 120, None, -320.0, 220.0
        elif total <= 12:
            main_size, sub_size, main_y, sub_y = 104, None, -320.0, 220.0
        elif total <= 18:
            main_size, sub_size, main_y, sub_y = 92, 60, -340.0, 230.0
        elif total <= 24:
            main_size, sub_size, main_y, sub_y = 80, 52, -340.0, 230.0
        else:
            main_size, sub_size, main_y, sub_y = 68, 44, -340.0, 230.0
    else:
        if total <= 10:
            main_size, sub_size, main_y, sub_y = 88, None, -140.0, 130.0
        elif total <= 16:
            main_size, sub_size, main_y, sub_y = 76, None, -140.0, 130.0
        elif total <= 24:
            main_size, sub_size, main_y, sub_y = 64, 40, -150.0, 130.0
        else:
            main_size, sub_size, main_y, sub_y = 54, 34, -150.0, 130.0
    return {
        "lines": lines,
        "main_size": main_size,
        "sub_size": sub_size,
        "main_y": main_y,
        "sub_y": sub_y,
    }


def _subtitle_transform_y(ui_position_y: float) -> float:
    """Convert a Jianying UI "position Y" value into the draft transform unit."""
    return ui_position_y / _JIANYING_UI_POSITION_SCALE


def _add_title_card(
    *,
    draft,
    script,
    cover_title: str,
    width: int,
    height: int,
    total_duration_us: int,
) -> None:
    """成片片头标题卡：主标题（+副标题）两行自适应。

    标题文本 = 封面标题去全部标点；总字数决定字号档位（见 title_layout）。
    标题黄色粗体、半透明黑底，居中；不注入剪映视频特效。
    """
    layout = title_layout(cover_title, width=width, height=height)
    lines = layout["lines"]  # type: ignore[assignment]
    main_size = layout["main_size"]  # type: ignore[assignment]
    sub_size = layout["sub_size"]  # type: ignore[assignment]
    main_y = layout["main_y"]  # type: ignore[assignment]
    sub_y = layout["sub_y"]  # type: ignore[assignment]

    title_us = min(_TITLE_LEADING_MS * 1000, total_duration_us)
    if title_us <= 0:
        return
    title_range = draft.Timerange(0, title_us)

    def _text(title_text: str, size: float, ui_y: float, track_name: str) -> None:
        segment = draft.TextSegment(
            title_text,
            title_range,
            style=draft.TextStyle(
                size=size,
                bold=True,
                color=(1.0, 0.84, 0.0),
                align=1,
                letter_spacing=0,
                line_spacing=0,
            ),
            background=draft.TextBackground(
                color="000000",
                alpha=0.32,
                round_radius=0.06,
                height=0.14,
                width=0.9,
            ),
            clip_settings=draft.ClipSettings(
                scale_x=1.0,
                scale_y=1.0,
                transform_x=0.0,
                transform_y=_subtitle_transform_y(ui_y),
                rotation=0.0,
            ),
        )
        script.add_segment(segment, track_name)

    _text(lines[0], float(main_size), float(main_y), "title_main")
    if len(lines) > 1 and sub_size:
        _text(lines[1], float(sub_size), float(sub_y), "title_sub")


def _otio_time_to_us(time: otio.opentime.RationalTime) -> int:
    """Convert an OTIO RationalTime to Jianying integer microseconds without rounding."""
    try:
        value = Fraction(str(time.value))
        rate = Fraction(str(time.rate))
        if rate == 0:
            raise ZeroDivisionError
        milliseconds = value * 1000 / rate
    except (ValueError, ZeroDivisionError) as exc:
        raise JianyingTimeError("OTIO time cannot be converted to integer milliseconds") from exc

    if milliseconds.denominator != 1:
        raise JianyingTimeError("Jianying export requires integer milliseconds")
    return milliseconds.numerator * 1000


def resolve_local_media_path(uri_or_path: str) -> Path:
    """Resolve a file URI or filesystem path and reject non-file media schemes."""
    if not uri_or_path.strip():
        raise JianyingMediaError("Jianying export requires a local media path")

    windows_path = PureWindowsPath(uri_or_path)
    if windows_path.drive and not uri_or_path.lower().startswith("file:"):
        return Path(uri_or_path).expanduser().resolve()

    parsed = urlparse(uri_or_path)
    if parsed.scheme and parsed.scheme.lower() != "file":
        raise JianyingMediaError("Jianying export supports local media only")

    if parsed.scheme.lower() == "file":
        decoded_path = url2pathname(unquote(parsed.path))
        if parsed.netloc and parsed.netloc.lower() != "localhost":
            decoded_path = f"//{parsed.netloc}{decoded_path}"
        return Path(decoded_path).expanduser().resolve()

    return Path(uri_or_path).expanduser().resolve()


def _required_uuid(metadata: dict[str, object], key: str) -> UUID:
    value = metadata.get(key)
    if not isinstance(value, str):
        raise JianyingWriteError(f"OTIO ClipAtlas metadata is missing {key}")
    try:
        return UUID(value)
    except ValueError as exc:
        raise JianyingWriteError(f"OTIO ClipAtlas metadata has invalid {key}") from exc


def _required_positive_int(metadata: dict[str, object], key: str) -> int:
    value = metadata.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise JianyingWriteError(f"OTIO ClipAtlas metadata has invalid {key}")
    return value


def _media_path(clip: otio.schema.Clip) -> Path:
    target_url = getattr(clip.media_reference, "target_url", None)
    if not isinstance(target_url, str):
        raise JianyingMediaError("Jianying export requires local clip media")
    path = resolve_local_media_path(target_url)
    if not path.is_file():
        raise JianyingMediaError(f"Jianying media file does not exist: {path}")
    return path


class PyJianYingDraftBackend:
    """Portable pyJianYingDraft adapter consuming only a validated OTIO timeline."""

    name = "pyJianYingDraft"
    version = "0.3.x"

    def export(
        self,
        timeline: otio.schema.Timeline,
        *,
        draft_name: str,
        settings: JianyingExportSettings,
    ) -> JianyingDraftArtifact:
        if settings.mode != JianyingMode.PORTABLE:
            raise JianyingConfigurationError(
                "PyJianYingDraftBackend portable export requires portable mode"
            )

        try:
            validate_draft_name(draft_name)
        except ValueError as exc:
            raise JianyingConfigurationError(str(exc)) from exc

        try:
            draft = import_module("pyJianYingDraft")
        except ModuleNotFoundError as exc:
            raise JianyingDependencyError("pyJianYingDraft is not installed") from exc

        metadata_value = timeline.metadata.get("clipatlas")
        try:
            metadata: dict[str, object] = dict(metadata_value)
        except (TypeError, ValueError) as exc:
            raise JianyingWriteError("OTIO timeline is missing ClipAtlas metadata") from exc
        plan_id = _required_uuid(metadata, "plan_id")
        project_id = _required_uuid(metadata, "project_id")
        narration_track_id = _required_uuid(metadata, "narration_track_id")
        total_duration_ms = _required_positive_int(metadata, "total_duration_ms")

        video_tracks = list(timeline.video_tracks())
        audio_tracks = list(timeline.audio_tracks())
        if len(video_tracks) != 1 or not video_tracks[0]:
            raise JianyingWriteError("Jianying export requires one non-empty video track")
        if len(audio_tracks) != 1 or len(audio_tracks[0]) != 1:
            raise JianyingWriteError("Jianying export requires one narration audio clip")

        video_entries: list[tuple[Path, int, int, int]] = []
        target_start_us = 0
        for item in video_tracks[0]:
            if not isinstance(item, otio.schema.Clip):
                raise JianyingWriteError("Jianying V0.1 video track supports clips only")
            source_range = item.source_range
            if source_range is None:
                raise JianyingTimeError("Jianying video clip is missing source range")
            source_start_us = _otio_time_to_us(source_range.start_time)
            duration_us = _otio_time_to_us(source_range.duration)
            video_entries.append((_media_path(item), target_start_us, source_start_us, duration_us))
            target_start_us += duration_us

        total_duration_us = total_duration_ms * 1000
        if target_start_us != total_duration_us:
            raise JianyingTimeError("Jianying video duration does not match OTIO total duration")

        narration_item = audio_tracks[0][0]
        if not isinstance(narration_item, otio.schema.Clip):
            raise JianyingWriteError("Jianying narration track supports a clip only")
        narration_range = narration_item.source_range
        if narration_range is None:
            raise JianyingTimeError("Jianying narration clip is missing source range")
        narration_source_start_us = _otio_time_to_us(narration_range.start_time)
        narration_duration_us = _otio_time_to_us(narration_range.duration)
        if narration_duration_us != total_duration_us:
            raise JianyingTimeError("Jianying narration duration does not match OTIO total duration")
        narration_path = _media_path(narration_item)

        draft_root = settings.draft_root.expanduser().resolve()
        try:
            draft_root.mkdir(parents=True, exist_ok=True)
            folder = draft.DraftFolder(str(draft_root))
            script = folder.create_draft(
                draft_name,
                settings.width,
                settings.height,
                allow_replace=False,
            )
            track_specs = [
                draft.TrackSpec(draft.TrackType.video, "main_video"),
                draft.TrackSpec(draft.TrackType.audio, "narration"),
            ]
            subtitle_entries = metadata.get("subtitles") or []
            if subtitle_entries:
                track_specs.append(draft.TrackSpec(draft.TrackType.text, "subtitles"))
            cover_title = (settings.cover_title or "").strip()
            if cover_title:
                # 片头标题卡主/副标题分轨（同轨时间重叠会被拒）。
                layout_hint = title_layout(cover_title, width=settings.width, height=settings.height)
                track_specs.append(draft.TrackSpec(draft.TrackType.text, "title_main"))
                if len(layout_hint["lines"]) > 1 and layout_hint["sub_size"]:
                    track_specs.append(draft.TrackSpec(draft.TrackType.text, "title_sub"))
            script.append_tracks(track_specs)
            for path, target_start, source_start, duration in video_entries:
                target_range = draft.Timerange(target_start, duration)
                try:
                    source_range = draft.Timerange(source_start, duration)
                    segment = draft.VideoSegment(
                        str(path),
                        target_range,
                        source_timerange=source_range,
                        volume=0.0,
                    )
                except ValueError as exc:
                    # Catalog ranges may overrun a source file by a few ms; clamp the
                    # source window end to the real material duration and retry once.
                    match = _MATERIAL_DURATION_RE.search(str(exc))
                    if match is None:
                        raise
                    material_us = int(match.group(1))
                    source_end = min(source_start + duration, material_us)
                    if source_end <= source_start:
                        raise
                    segment = draft.VideoSegment(
                        str(path),
                        target_range,
                        source_timerange=draft.Timerange(source_start, source_end - source_start),
                        volume=0.0,
                    )
                script.add_segment(segment, "main_video")

            narration_segment = draft.AudioSegment(
                str(narration_path),
                draft.Timerange(0, narration_duration_us),
                source_timerange=draft.Timerange(
                    narration_source_start_us,
                    narration_duration_us,
                ),
            )
            script.add_segment(narration_segment, "narration")
            for subtitle in subtitle_entries:
                try:
                    subtitle_start = int(subtitle["start_ms"]) * 1000
                    subtitle_end = int(subtitle["end_ms"]) * 1000
                except (KeyError, TypeError, ValueError) as exc:
                    raise JianyingWriteError(f"Jianying subtitle metadata is invalid: {exc}") from exc
                text = str(subtitle.get("text", "")).strip()
                if not text or subtitle_end <= subtitle_start:
                    raise JianyingWriteError("Jianying subtitle metadata is invalid: empty or malformed entry")
                subtitle_segment = draft.TextSegment(
                    text,
                    draft.Timerange(subtitle_start, subtitle_end - subtitle_start),
                    style=draft.TextStyle(
                        size=8.0,
                        bold=False,
                        color=(1.0, 1.0, 1.0),
                        align=1,
                        letter_spacing=0,
                        line_spacing=0,
                    ),
                    clip_settings=draft.ClipSettings(
                        scale_x=0.69,
                        scale_y=0.69,
                        transform_x=0.0,
                        transform_y=_subtitle_transform_y(-879.0),
                        rotation=0.0,
                    ),
                )
                script.add_segment(subtitle_segment, "subtitles")

            if cover_title:
                _add_title_card(
                    draft=draft,
                    script=script,
                    cover_title=cover_title,
                    width=settings.width,
                    height=settings.height,
                    total_duration_us=total_duration_us,
                )
            script.save()
        except FileExistsError as exc:
            raise JianyingConfigurationError(
                "Draft already exists; choose a different draft name"
            ) from exc
        except (FileNotFoundError, ValueError) as exc:
            raise JianyingMediaError(f"Jianying rejected local media: {exc}") from exc
        except JianyingMediaError:
            raise
        except Exception as exc:
            raise JianyingWriteError(f"failed to create Jianying draft: {exc}") from exc

        try:
            backend_version = package_version("pyJianYingDraft")
        except PackageNotFoundError:
            backend_version = self.version

        return JianyingDraftArtifact(
            plan_id=plan_id,
            project_id=project_id,
            narration_track_id=narration_track_id,
            draft_name=draft_name,
            output_path=(draft_root / draft_name).resolve(),
            mode=settings.mode,
            backend_name=self.name,
            backend_version=backend_version,
            total_duration_ms=total_duration_ms,
        )


__all__ = [
    "JianyingExportSettings",
    "JianyingMediaError",
    "JianyingMode",
    "JianyingTimeError",
    "PyJianYingDraftBackend",
    "resolve_local_media_path",
]

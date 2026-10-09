import json
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from clipatlas.video.commands import AsyncCommandRunner, SubprocessCommandRunner
from clipatlas.video.models import MediaMetadata


class MediaProbeError(RuntimeError):
    """Raised when ffprobe cannot produce usable video metadata."""


def _parse_fps(value: str) -> float:
    try:
        if "/" in value:
            numerator_text, denominator_text = value.split("/", 1)
            numerator = float(numerator_text)
            denominator = float(denominator_text)
            if denominator == 0:
                raise ValueError("zero denominator")
            fps = numerator / denominator
        else:
            fps = float(value)
    except (TypeError, ValueError) as exc:
        raise MediaProbeError("ffprobe returned an invalid frame rate") from exc
    if fps <= 0:
        raise MediaProbeError("ffprobe returned a non-positive frame rate")
    return fps


class MediaProbe:
    def __init__(self, runner: AsyncCommandRunner | None = None) -> None:
        self._runner = runner or SubprocessCommandRunner()

    async def probe(self, path: Path) -> MediaMetadata:
        args = [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
        result = await self._runner.run(args)
        if result.returncode != 0:
            detail = result.stderr.strip() or "unknown ffprobe error"
            raise MediaProbeError(f"ffprobe failed: {detail}")

        try:
            payload = json.loads(result.stdout)
        except JSONDecodeError as exc:
            raise MediaProbeError("ffprobe returned invalid JSON") from exc

        if not isinstance(payload, dict):
            raise MediaProbeError("ffprobe returned an invalid payload")

        streams = payload.get("streams")
        if not isinstance(streams, list):
            raise MediaProbeError("ffprobe output is missing streams")

        video_stream: dict[str, Any] | None = None
        has_audio = False
        for stream in streams:
            if not isinstance(stream, dict):
                continue
            if stream.get("codec_type") == "video" and video_stream is None:
                video_stream = stream
            elif stream.get("codec_type") == "audio":
                has_audio = True

        if video_stream is None:
            raise MediaProbeError("ffprobe output has no video stream")

        media_format = payload.get("format")
        if not isinstance(media_format, dict):
            raise MediaProbeError("ffprobe output is missing format metadata")

        try:
            duration_ms = round(float(media_format["duration"]) * 1000)
            width = int(video_stream["width"])
            height = int(video_stream["height"])
            codec = str(video_stream["codec_name"])
            fps = _parse_fps(str(video_stream["avg_frame_rate"]))
            return MediaMetadata(
                duration_ms=duration_ms,
                width=width,
                height=height,
                fps=fps,
                video_codec=codec,
                has_audio=has_audio,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise MediaProbeError("ffprobe returned incomplete video metadata") from exc

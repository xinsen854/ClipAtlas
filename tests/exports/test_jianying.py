import ast
import base64
import json
import wave
from pathlib import Path
from uuid import uuid4

import opentimelineio as otio
import pytest
from pydantic import ValidationError

from clipatlas.exports.contracts import JianyingBackend
from clipatlas.exports.errors import JianyingConfigurationError
from clipatlas.exports.jianying import (
    JianyingExportSettings,
    JianyingMediaError,
    JianyingMode,
    JianyingTimeError,
    PyJianYingDraftBackend,
    _otio_time_to_us,
    resolve_local_media_path,
)


def _write_png(path: Path) -> None:
    path.write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFElEQVR4nGP8z8DAwMDAxMDAwAIAAwAB/5nQxQAAAABJRU5ErkJggg=="
        )
    )


def _write_silent_wav(path: Path, duration_ms: int) -> None:
    sample_rate = 8000
    frame_count = sample_rate * duration_ms // 1000
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * frame_count)


def _portable_timeline(video_path: Path, narration_path: Path) -> otio.schema.Timeline:
    plan_id = uuid4()
    project_id = uuid4()
    narration_track_id = uuid4()
    timeline = otio.schema.Timeline(name="portable-jianying-test")
    timeline.metadata["clipatlas"] = {
        "plan_id": str(plan_id),
        "project_id": str(project_id),
        "narration_track_id": str(narration_track_id),
        "narration_revision": 1,
        "rough_cut_revision": 2,
        "total_duration_ms": 3000,
        "timing_rate": 1000,
    }

    video_track = otio.schema.Track(name="Video", kind=otio.schema.TrackKind.Video)
    for source_start_ms, duration_ms in ((5000, 1000), (9000, 2000)):
        source_range = otio.opentime.TimeRange(
            otio.opentime.RationalTime(source_start_ms, 1000),
            otio.opentime.RationalTime(duration_ms, 1000),
        )
        video_track.append(
            otio.schema.Clip(
                name=f"clip-{source_start_ms}",
                media_reference=otio.schema.ExternalReference(
                    target_url=video_path.resolve().as_uri(),
                    available_range=source_range,
                ),
                source_range=source_range,
            )
        )

    audio_range = otio.opentime.TimeRange(
        otio.opentime.RationalTime(0, 1000),
        otio.opentime.RationalTime(3000, 1000),
    )
    audio_track = otio.schema.Track(name="Narration", kind=otio.schema.TrackKind.Audio)
    audio_track.append(
        otio.schema.Clip(
            name="Narration",
            media_reference=otio.schema.ExternalReference(
                target_url=narration_path.resolve().as_uri(),
                available_range=audio_range,
            ),
            source_range=audio_range,
        )
    )
    timeline.tracks.extend([video_track, audio_track])
    return timeline


def test_otio_time_to_us_preserves_exact_integer_milliseconds() -> None:
    assert _otio_time_to_us(otio.opentime.RationalTime(83_420, 1000)) == 83_420_000
    assert _otio_time_to_us(otio.opentime.RationalTime(5750, 1000)) == 5_750_000


def test_otio_time_to_us_rejects_fractional_milliseconds() -> None:
    with pytest.raises(JianyingTimeError, match="integer milliseconds"):
        _otio_time_to_us(otio.opentime.RationalTime(1, 24))


def test_resolve_local_media_path_accepts_file_uri_and_local_path(tmp_path: Path) -> None:
    media = tmp_path / "素材 01.mp4"
    media.write_bytes(b"fixture")

    assert resolve_local_media_path(media.as_uri()) == media.resolve()
    assert resolve_local_media_path(str(media)) == media.resolve()


@pytest.mark.parametrize(
    "uri",
    [
        "https://example.com/video.mp4",
        "http://example.com/video.mp4",
        "s3://bucket/video.mp4",
    ],
)
def test_resolve_local_media_path_rejects_remote_media(uri: str) -> None:
    with pytest.raises(JianyingMediaError, match="local media"):
        resolve_local_media_path(uri)


def test_portable_settings_require_valid_dimensions_and_draft_root(tmp_path: Path) -> None:
    settings = JianyingExportSettings(draft_root=tmp_path / "drafts", width=1920, height=1080)

    assert settings.mode == JianyingMode.PORTABLE
    assert settings.width == 1920
    assert settings.height == 1080

    with pytest.raises(ValidationError):
        JianyingExportSettings(draft_root=tmp_path / "drafts", width=0, height=1080)


def test_jianying_pro_10_8_requires_explicit_local_configuration(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="install_dir"):
        JianyingExportSettings(
            draft_root=tmp_path / "drafts",
            mode=JianyingMode.JIANYING_PRO_10_8,
        )

    settings = JianyingExportSettings(
        draft_root=tmp_path / "drafts",
        mode=JianyingMode.JIANYING_PRO_10_8,
        install_dir=tmp_path / "JianyingPro",
        user_data_dir=tmp_path / "user-data",
    )
    assert settings.install_dir == tmp_path / "JianyingPro"
    assert settings.user_data_dir == tmp_path / "user-data"


def test_pyjianyingdraft_portable_backend_preserves_track_order_and_timing(
    tmp_path: Path,
) -> None:
    video_path = tmp_path / "source.png"
    narration_path = tmp_path / "narration.wav"
    _write_png(video_path)
    _write_silent_wav(narration_path, 3000)
    timeline = _portable_timeline(video_path, narration_path)
    settings = JianyingExportSettings(draft_root=tmp_path / "drafts")

    artifact = PyJianYingDraftBackend().export(
        timeline,
        draft_name="ClipAtlas Portable",
        settings=settings,
    )

    draft_content_path = artifact.output_path / "draft_content.json"
    assert draft_content_path.is_file()
    content = json.loads(draft_content_path.read_text(encoding="utf-8"))
    tracks = {track["name"]: track for track in content["tracks"]}
    assert set(tracks) == {"main_video", "narration"}
    assert tracks["main_video"]["type"] == "video"
    assert tracks["narration"]["type"] == "audio"

    video_segments = tracks["main_video"]["segments"]
    assert [segment["target_timerange"] for segment in video_segments] == [
        {"start": 0, "duration": 1_000_000},
        {"start": 1_000_000, "duration": 2_000_000},
    ]
    assert [segment["source_timerange"] for segment in video_segments] == [
        {"start": 5_000_000, "duration": 1_000_000},
        {"start": 9_000_000, "duration": 2_000_000},
    ]
    narration_segments = tracks["narration"]["segments"]
    assert len(narration_segments) == 1
    assert narration_segments[0]["target_timerange"] == {
        "start": 0,
        "duration": 3_000_000,
    }
    assert str(artifact.plan_id) == timeline.metadata["clipatlas"]["plan_id"]
    assert artifact.total_duration_ms == 3000


def test_jianying_backend_contract_exposes_export_operation() -> None:
    assert hasattr(JianyingBackend, "export")


def test_export_preserves_existing_draft(tmp_path: Path) -> None:
    video_path, audio_path = tmp_path / "source.png", tmp_path / "narration.wav"
    _write_png(video_path)
    _write_silent_wav(audio_path, 3000)
    settings = JianyingExportSettings(draft_root=tmp_path / "drafts")
    existing = settings.draft_root / "Existing draft"
    existing.mkdir(parents=True)
    sentinel = existing / "user-edits.txt"
    sentinel.write_text("preserve user edits", encoding="utf-8")

    with pytest.raises(JianyingConfigurationError, match="already exists"):
        PyJianYingDraftBackend().export(
            _portable_timeline(video_path, audio_path),
            draft_name=existing.name, settings=settings,
        )
    assert sentinel.read_text(encoding="utf-8") == "preserve user edits"
    assert list(existing.iterdir()) == [sentinel]


@pytest.mark.parametrize("name", [".", "..", "C:", "NUL", "invalid."])
def test_backend_rejects_unsafe_name_before_writing(tmp_path: Path, name: str) -> None:
    with pytest.raises(JianyingConfigurationError, match="folder name"):
        PyJianYingDraftBackend().export(
            otio.schema.Timeline(), draft_name=name,
            settings=JianyingExportSettings(draft_root=tmp_path / "drafts"),
        )
    assert not (tmp_path / "drafts").exists()


def test_jianying_module_has_no_forbidden_upstream_imports() -> None:
    import clipatlas.exports.jianying as jianying_module

    source_path = Path(jianying_module.__file__).resolve()
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)
        elif isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)

    forbidden_prefixes = (
        "clipatlas.search",
        "clipatlas.roughcut.planner",
        "clipatlas.roughcut.scoring",
        "clipatlas.speech.service",
        "clipatlas.speech.providers",
    )
    assert not any(
        module == prefix or module.startswith(f"{prefix}.")
        for module in imported_modules
        for prefix in forbidden_prefixes
    )

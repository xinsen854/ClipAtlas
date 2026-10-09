from pathlib import Path

from clipatlas.catalog.store import CatalogStore
from clipatlas.domain.models import VideoAsset
from clipatlas.video.models import IngestedVideo, MediaMetadata


def test_video_fallback_role_is_explicit_and_persistent(tmp_path: Path) -> None:
    store = CatalogStore(tmp_path / "library.sqlite3")
    video = VideoAsset(
        filename="neutral.mp4", source_uri="file:///neutral.mp4", duration_ms=5000,
        width=1920, height=1080, fps=25,
    )
    prepared = IngestedVideo(
        video=video,
        metadata=MediaMetadata(
            duration_ms=5000, width=1920, height=1080, fps=25,
            video_codec="h264", has_audio=False,
        ),
        segments=[], frames_by_segment={},
    )
    store.save_prepared_video(prepared)

    assert store.get_video(video.id).fallback_role == "normal"  # type: ignore[union-attr]
    store.set_video_fallback_role(video.id, "generic")
    assert store.get_video(video.id).fallback_role == "generic"  # type: ignore[union-attr]

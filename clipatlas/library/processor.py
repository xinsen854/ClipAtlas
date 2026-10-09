import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Protocol
from uuid import UUID

from clipatlas.domain.models import SegmentSource, VideoAsset, VideoSegment
from clipatlas.library.models import LibraryItemStatus
from clipatlas.video.commands import AsyncCommandRunner
from clipatlas.video.frames import FrameExtractor
from clipatlas.video.models import IngestedVideo, MediaMetadata
from clipatlas.video.scenes import SceneRange


class MediaProbeLike(Protocol):
    async def probe(self, path: Path) -> MediaMetadata: ...


class SceneDetectorLike(Protocol):
    def detect(self, path: Path, duration_ms: int) -> list[SceneRange]: ...


StageCallback = Callable[[LibraryItemStatus], None]


class LocalFilePreparationService:
    def __init__(
        self,
        probe: MediaProbeLike,
        scene_detector: SceneDetectorLike,
        cache_root: Path,
        runner: AsyncCommandRunner,
    ) -> None:
        self._probe = probe
        self._scene_detector = scene_detector
        self._cache_root = cache_root.resolve()
        self._frame_extractor = FrameExtractor(runner=runner)

    async def prepare(
        self,
        item_id: UUID,
        source_path: Path,
        on_stage: StageCallback,
    ) -> IngestedVideo:
        source = source_path.resolve(strict=True)

        on_stage(LibraryItemStatus.PROBING)
        metadata = await self._probe.probe(source)
        video = VideoAsset(
            filename=source.name,
            source_uri=source.as_uri(),
            duration_ms=metadata.duration_ms,
            width=metadata.width,
            height=metadata.height,
            fps=metadata.fps,
        )

        on_stage(LibraryItemStatus.SCENE_DETECTION)
        scene_ranges = await asyncio.to_thread(
            self._scene_detector.detect,
            source,
            metadata.duration_ms,
        )
        segments = [
            VideoSegment(
                video_id=video.id,
                start_ms=scene.start_ms,
                end_ms=scene.end_ms,
                source=SegmentSource.SCENE_DETECTION,
            )
            for scene in scene_ranges
        ]

        on_stage(LibraryItemStatus.FRAME_EXTRACTION)
        frame_root = self._cache_root / str(item_id) / "frames"
        frames_by_segment: dict[UUID, list[str]] = {}
        for segment in segments:
            frame_paths = await self._frame_extractor.extract(
                source=source,
                segment_id=segment.id,
                start_ms=segment.start_ms,
                end_ms=segment.end_ms,
                frame_root=frame_root,
            )
            frames_by_segment[segment.id] = [path.resolve().as_uri() for path in frame_paths]

        return IngestedVideo(
            video=video,
            metadata=metadata,
            segments=segments,
            frames_by_segment=frames_by_segment,
        )

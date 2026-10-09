from collections.abc import AsyncIterator
from uuid import UUID, uuid4

from clipatlas.domain.models import SegmentSource, VideoAsset, VideoSegment
from clipatlas.video.frames import FrameExtractor
from clipatlas.video.models import IngestedVideo
from clipatlas.video.probe import MediaProbe
from clipatlas.video.scenes import SceneDetector
from clipatlas.video.storage import LocalVideoStore


class VideoIngestService:
    def __init__(
        self,
        store: LocalVideoStore,
        probe: MediaProbe,
        scene_detector: SceneDetector,
        frame_extractor: FrameExtractor,
    ) -> None:
        self._store = store
        self._probe = probe
        self._scene_detector = scene_detector
        self._frame_extractor = frame_extractor

    async def ingest(
        self,
        source_name: str,
        chunks: AsyncIterator[bytes],
    ) -> IngestedVideo:
        video_id = uuid4()
        stored = await self._store.save(video_id=video_id, source_name=source_name, chunks=chunks)
        metadata = await self._probe.probe(stored.path)

        video = VideoAsset(
            id=video_id,
            filename=source_name,
            source_uri=stored.path.resolve().as_uri(),
            duration_ms=metadata.duration_ms,
            width=metadata.width,
            height=metadata.height,
            fps=metadata.fps,
        )

        scene_ranges = self._scene_detector.detect(stored.path, metadata.duration_ms)
        segments: list[VideoSegment] = []
        frames_by_segment: dict[UUID, list[str]] = {}

        for scene in scene_ranges:
            segment = VideoSegment(
                video_id=video_id,
                start_ms=scene.start_ms,
                end_ms=scene.end_ms,
                source=SegmentSource.SCENE_DETECTION,
            )
            segments.append(segment)
            frame_paths = await self._frame_extractor.extract(
                source=stored.path,
                segment_id=segment.id,
                start_ms=segment.start_ms,
                end_ms=segment.end_ms,
            )
            frames_by_segment[segment.id] = [path.resolve().as_uri() for path in frame_paths]

        return IngestedVideo(
            video=video,
            metadata=metadata,
            segments=segments,
            frames_by_segment=frames_by_segment,
        )

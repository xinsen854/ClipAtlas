from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from clipatlas.domain.models import SegmentSource, VideoAsset, VideoSegment
from clipatlas.main import create_app
from clipatlas.video.models import IngestedVideo, MediaMetadata


class FakeVideoIngestService:
    def __init__(self, result: IngestedVideo) -> None:
        self.result = result
        self.source_name: str | None = None
        self.payload = b""

    async def ingest(self, source_name, chunks):
        self.source_name = source_name
        collected = bytearray()
        async for chunk in chunks:
            collected.extend(chunk)
        self.payload = bytes(collected)
        return self.result


def _result() -> IngestedVideo:
    video_id = uuid4()
    segment = VideoSegment(
        video_id=video_id,
        start_ms=0,
        end_ms=2_500,
        source=SegmentSource.SCENE_DETECTION,
    )
    return IngestedVideo(
        video=VideoAsset(
            id=video_id,
            filename="sample.mp4",
            source_uri="file:///tmp/sample.mp4",
            duration_ms=2_500,
            width=1280,
            height=720,
            fps=25.0,
        ),
        metadata=MediaMetadata(
            duration_ms=2_500,
            width=1280,
            height=720,
            fps=25.0,
            video_codec="h264",
            has_audio=True,
        ),
        segments=[segment],
        frames_by_segment={segment.id: ["file:///tmp/frame.jpg"]},
    )


def test_upload_video_streams_file_to_ingest_service_and_returns_result() -> None:
    fake = FakeVideoIngestService(_result())
    app = create_app()
    app.state.video_ingest_service = fake
    client = TestClient(app)

    response = client.post(
        "/api/v1/videos",
        files={"file": ("sample.mp4", b"video-data", "video/mp4")},
    )

    assert response.status_code == 201
    assert fake.source_name == "sample.mp4"
    assert fake.payload == b"video-data"
    body = response.json()
    assert UUID(body["video"]["id"]) == fake.result.video.id
    assert body["video"]["filename"] == "sample.mp4"
    assert body["metadata"]["duration_ms"] == 2_500
    assert body["segments"][0]["start_ms"] == 0
    assert body["segments"][0]["end_ms"] == 2_500
    assert body["frames_by_segment"][str(fake.result.segments[0].id)] == [
        "file:///tmp/frame.jpg"
    ]

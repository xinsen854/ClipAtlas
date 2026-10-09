from uuid import uuid4

import pytest

from clipatlas.domain.models import AnnotationOrigin
from clipatlas.providers.contracts import AnalyzeSegmentRequest
from clipatlas.providers.fake import FakeVideoUnderstandingProvider


@pytest.mark.asyncio
async def test_fake_provider_returns_deterministic_annotation():
    provider = FakeVideoUnderstandingProvider()
    segment_id = uuid4()
    request = AnalyzeSegmentRequest(
        video_id=uuid4(),
        segment_id=segment_id,
        start_ms=1000,
        end_ms=4000,
        source_uri="file:///video.mp4",
    )

    result = await provider.analyze_segment(request)

    assert result.provider == "fake"
    assert result.annotation.provider == "fake"
    assert result.annotation.origin == AnnotationOrigin.AI
    assert result.annotation.segment_id == segment_id
    assert result.annotation.description == "Synthetic semantic description for test segment"
    assert result.annotation.raw_payload["start_ms"] == 1000
    assert result.annotation.raw_payload["end_ms"] == 4000


def test_fake_provider_declares_only_supported_capabilities():
    provider = FakeVideoUnderstandingProvider()

    assert provider.capabilities.image_input is True
    assert provider.capabilities.structured_output is True
    assert provider.capabilities.native_video_input is False
    assert provider.capabilities.temporal_search is False

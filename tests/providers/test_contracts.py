from uuid import uuid4

import pytest

from clipatlas.domain.models import ObjectiveFact
from clipatlas.providers.contracts import AnalyzeSegmentRequest, ProviderCapabilities
from clipatlas.providers.evidence_contract import (
    SemanticLanguageError,
    semantic_language_issues,
    validate_semantic_language,
)


def test_analyze_segment_request_preserves_clipatlas_time_range_and_frames():
    video_id = uuid4()
    segment_id = uuid4()

    request = AnalyzeSegmentRequest(
        video_id=video_id,
        segment_id=segment_id,
        start_ms=250,
        end_ms=2250,
        source_uri="s3://bucket/video.mp4",
        frame_uris=["s3://bucket/frame-1.jpg", "s3://bucket/frame-2.jpg"],
        context={"language": "zh-CN"},
    )

    assert request.video_id == video_id
    assert request.segment_id == segment_id
    assert request.start_ms == 250
    assert request.end_ms == 2250
    assert len(request.frame_uris) == 2


def test_provider_capabilities_default_to_false():
    capabilities = ProviderCapabilities()

    assert capabilities.native_video_input is False
    assert capabilities.image_input is False
    assert capabilities.temporal_search is False
    assert capabilities.structured_output is False


def test_semantic_language_accepts_chinese_models_acronyms_and_original_ocr() -> None:
    fields = {
        "description": "BJ40 SUV正在泥地越野，ADS功能界面清晰可见",
        "characters": [],
        "actions": ["越野行驶"],
        "scene": ["泥地"],
        "emotions": [],
        "objects": ["BJ40", "激光雷达"],
        "facts": [ObjectiveFact(layer="subject", value="BJ40")],
    }

    assert semantic_language_issues(**fields) == []
    validate_semantic_language(**fields)

    model_fields = {**fields, "objects": ["Tank 700", "Land Rover", "BJ40"]}
    assert semantic_language_issues(**model_fields) == []


def test_semantic_language_rejects_untranslated_prose_but_ocr_is_not_checked() -> None:
    fields = {
        "description": "An off-road vehicle drives through deep mud",
        "characters": [],
        "actions": ["driving through mud"],
        "scene": ["泥地"],
        "emotions": [],
        "objects": ["SUV"],
        "facts": [],
    }

    with pytest.raises(SemanticLanguageError, match="description"):
        validate_semantic_language(**fields)

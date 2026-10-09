from uuid import uuid4

import pytest
from pydantic import ValidationError

from clipatlas.retrieval.models import VideoChunkEmbedding


def test_video_chunk_embedding_accepts_matching_dimension() -> None:
    record = VideoChunkEmbedding(
        video_id=uuid4(),
        start_ms=0,
        end_ms=30_000,
        provider="qwen-vl-video",
        model="qwen3-vl-embedding",
        dimensions=2560,
        chunk_duration_ms=30_000,
        overlap_ms=5_000,
        vector=[1.0] + [0.0] * 2559,
    )

    assert record.dimensions == 2560
    assert len(record.vector) == 2560


def test_video_chunk_embedding_rejects_dimension_mismatch() -> None:
    with pytest.raises(ValidationError, match="vector length must match dimensions"):
        VideoChunkEmbedding(
            video_id=uuid4(),
            start_ms=0,
            end_ms=30_000,
            provider="qwen-vl-video",
            model="qwen3-vl-embedding",
            dimensions=2560,
            chunk_duration_ms=30_000,
            overlap_ms=5_000,
            vector=[1.0, 0.0],
        )


def test_video_chunk_embedding_rejects_empty_or_reversed_span() -> None:
    with pytest.raises(ValidationError, match="end_ms must be greater than start_ms"):
        VideoChunkEmbedding(
            video_id=uuid4(),
            start_ms=30_000,
            end_ms=30_000,
            provider="qwen-vl-video",
            model="qwen3-vl-embedding",
            dimensions=2,
            chunk_duration_ms=30_000,
            overlap_ms=5_000,
            vector=[1.0, 0.0],
        )


def test_video_chunk_embedding_rejects_invalid_overlap() -> None:
    with pytest.raises(ValidationError, match="overlap_ms must be smaller"):
        VideoChunkEmbedding(
            video_id=uuid4(),
            start_ms=0,
            end_ms=5_000,
            provider="qwen-vl-video",
            model="qwen3-vl-embedding",
            dimensions=2,
            chunk_duration_ms=5_000,
            overlap_ms=5_000,
            vector=[1.0, 0.0],
        )

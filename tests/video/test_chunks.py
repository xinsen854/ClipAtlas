import pytest

from clipatlas.video.chunks import VideoChunkSpan, plan_video_chunks


def test_short_video_is_one_chunk() -> None:
    assert plan_video_chunks(10_000) == [VideoChunkSpan(start_ms=0, end_ms=10_000)]


def test_seventy_second_video_uses_30s_chunks_with_5s_overlap() -> None:
    assert plan_video_chunks(70_000) == [
        VideoChunkSpan(start_ms=0, end_ms=30_000),
        VideoChunkSpan(start_ms=25_000, end_ms=55_000),
        VideoChunkSpan(start_ms=50_000, end_ms=70_000),
    ]


def test_exact_chunk_duration_is_not_duplicated() -> None:
    assert plan_video_chunks(30_000) == [VideoChunkSpan(start_ms=0, end_ms=30_000)]


@pytest.mark.parametrize(
    ("duration_ms", "chunk_duration_ms", "overlap_ms"),
    [
        (0, 30_000, 5_000),
        (30_000, 0, 0),
        (30_000, 30_000, -1),
        (30_000, 30_000, 30_000),
        (30_000, 30_000, 31_000),
    ],
)
def test_invalid_chunk_parameters_are_rejected(
    duration_ms: int,
    chunk_duration_ms: int,
    overlap_ms: int,
) -> None:
    with pytest.raises(ValueError):
        plan_video_chunks(
            duration_ms,
            chunk_duration_ms=chunk_duration_ms,
            overlap_ms=overlap_ms,
        )

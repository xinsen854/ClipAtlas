from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class VideoIndexProfile:
    key: str
    chunk_duration_ms: int
    overlap_ms: int

    def __post_init__(self) -> None:
        if self.chunk_duration_ms <= 0:
            raise ValueError("chunk_duration_ms must be positive")
        if self.overlap_ms < 0 or self.overlap_ms >= self.chunk_duration_ms:
            raise ValueError("overlap_ms must be non-negative and smaller than chunk duration")


FINE_5S_PROFILE = VideoIndexProfile(
    key="5s",
    chunk_duration_ms=5_000,
    overlap_ms=1_000,
)
COARSE_30S_PROFILE = VideoIndexProfile(
    key="30s",
    chunk_duration_ms=30_000,
    overlap_ms=5_000,
)
DEFAULT_VIDEO_INDEX_PROFILE = FINE_5S_PROFILE
VIDEO_INDEX_PROFILES: dict[str, VideoIndexProfile] = {
    FINE_5S_PROFILE.key: FINE_5S_PROFILE,
    COARSE_30S_PROFILE.key: COARSE_30S_PROFILE,
}


def get_video_index_profile(key: str) -> VideoIndexProfile:
    try:
        return VIDEO_INDEX_PROFILES[key]
    except KeyError as exc:
        raise ValueError(f"unsupported video index profile: {key}") from exc

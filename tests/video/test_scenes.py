from pathlib import Path

from clipatlas.video.scenes import SceneDetector, SceneRange


def test_scene_detector_normalizes_ranges_to_clipatlas_milliseconds() -> None:
    seen_paths: list[Path] = []

    def raw_detector(path: Path) -> list[tuple[float, float]]:
        seen_paths.append(path)
        return [
            (0.0, 1.2344),
            (1.2344, 3.5),
            (3.5, 12.0),
        ]

    detector = SceneDetector(raw_detector=raw_detector)

    result = detector.detect(Path("/tmp/video.mp4"), duration_ms=10_000)

    assert seen_paths == [Path("/tmp/video.mp4")]
    assert result == [
        SceneRange(start_ms=0, end_ms=1_234),
        SceneRange(start_ms=1_234, end_ms=3_500),
        SceneRange(start_ms=3_500, end_ms=10_000),
    ]


def test_scene_detector_removes_zero_length_and_repairs_overlap() -> None:
    detector = SceneDetector(
        raw_detector=lambda _path: [
            (0.0, 2.0),
            (1.9, 4.0),
            (4.0, 4.0),
            (4.0, 12.0),
        ]
    )

    result = detector.detect(Path("/tmp/video.mp4"), duration_ms=10_000)

    assert result == [
        SceneRange(start_ms=0, end_ms=2_000),
        SceneRange(start_ms=2_000, end_ms=4_000),
        SceneRange(start_ms=4_000, end_ms=10_000),
    ]


def test_scene_detector_falls_back_to_full_video_when_no_valid_scene_exists() -> None:
    detector = SceneDetector(raw_detector=lambda _path: [])

    result = detector.detect(Path("/tmp/video.mp4"), duration_ms=8_750)

    assert result == [SceneRange(start_ms=0, end_ms=8_750)]

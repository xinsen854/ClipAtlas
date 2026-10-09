from collections.abc import Callable, Sequence
from pathlib import Path

from pydantic import BaseModel, Field, model_validator


class SceneRange(BaseModel):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_range(self) -> "SceneRange":
        if self.end_ms <= self.start_ms:
            raise ValueError("scene end_ms must be greater than start_ms")
        return self


RawSceneDetector = Callable[[Path], Sequence[tuple[float, float]]]


def _pyscenedetect(path: Path) -> list[tuple[float, float]]:
    from scenedetect import ContentDetector, detect  # type: ignore[import-untyped]

    scenes = detect(str(path), ContentDetector())
    return [(float(start.get_seconds()), float(end.get_seconds())) for start, end in scenes]


class SceneDetector:
    def __init__(self, raw_detector: RawSceneDetector | None = None) -> None:
        self._raw_detector = raw_detector or _pyscenedetect

    def detect(self, path: Path, duration_ms: int) -> list[SceneRange]:
        if duration_ms <= 0:
            raise ValueError("duration_ms must be positive")

        normalized: list[SceneRange] = []
        previous_end = 0

        for raw_start_seconds, raw_end_seconds in self._raw_detector(path):
            raw_start_ms = round(raw_start_seconds * 1000)
            raw_end_ms = round(raw_end_seconds * 1000)

            start_ms = max(0, previous_end, raw_start_ms)
            end_ms = min(duration_ms, raw_end_ms)

            if start_ms >= duration_ms:
                break
            if end_ms <= start_ms:
                continue

            normalized.append(SceneRange(start_ms=start_ms, end_ms=end_ms))
            previous_end = end_ms

        if not normalized:
            return [SceneRange(start_ms=0, end_ms=duration_ms)]
        return normalized

import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

_SAFE_EXTENSION = re.compile(r"^\.[a-z0-9]{1,10}$")


@dataclass(frozen=True, slots=True)
class StoredVideo:
    video_id: UUID
    path: Path
    source_name: str


class LocalVideoStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    async def save(
        self,
        video_id: UUID,
        source_name: str,
        chunks: AsyncIterator[bytes],
    ) -> StoredVideo:
        suffix = Path(source_name).suffix.lower()
        extension = suffix if _SAFE_EXTENSION.fullmatch(suffix) else ".bin"
        directory = self._root / str(video_id)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"source{extension}"
        with target.open("wb") as output:
            async for chunk in chunks:
                if chunk:
                    output.write(chunk)
        return StoredVideo(video_id=video_id, path=target, source_name=source_name)

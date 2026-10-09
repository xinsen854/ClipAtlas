"""Dead-letter queue for chunks that repeatedly fail to embed.

Stored as a JSON file so entries survive process restarts. Chunks in the
DLQ are skipped by default on subsequent index runs — use `--retry-failed`
to re-attempt them.
"""

import json
import time
from pathlib import Path

DEFAULT_DLQ_PATH = Path.home() / ".sentrysearch" / "dlq.json"


class DeadLetterQueue:
    """Persistent record of chunks that could not be embedded."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else DEFAULT_DLQ_PATH
        self._entries: dict[str, dict] = {}
        if self.path.exists():
            try:
                self._entries = json.loads(self.path.read_text())
            except (json.JSONDecodeError, OSError):
                self._entries = {}

    def contains(self, chunk_id: str) -> bool:
        return chunk_id in self._entries

    def record(
        self,
        chunk_id: str,
        *,
        source_file: str,
        start_time: float,
        end_time: float,
        error: str,
        attempts: int,
    ) -> None:
        self._entries[chunk_id] = {
            "source_file": source_file,
            "start_time": float(start_time),
            "end_time": float(end_time),
            "error": str(error)[:500],
            "attempts": int(attempts),
            "last_attempt": time.time(),
        }
        self._flush()

    def remove(self, chunk_id: str) -> bool:
        if chunk_id in self._entries:
            del self._entries[chunk_id]
            self._flush()
            return True
        return False

    def clear(self) -> int:
        count = len(self._entries)
        self._entries.clear()
        self._flush()
        return count

    def entries(self) -> dict[str, dict]:
        return dict(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def _flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._entries, indent=2, sort_keys=True))
        tmp.replace(self.path)

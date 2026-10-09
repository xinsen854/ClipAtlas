import sqlite3
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from uuid import UUID

from clipatlas.domain.models import utc_now
from clipatlas.library.fingerprint import canonicalize_path
from clipatlas.retrieval.video_profiles import DEFAULT_VIDEO_INDEX_PROFILE


class PreparedMediaCheckpointStore:
    """Maps one library item version to its already prepared ClipAtlas video."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = canonicalize_path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS catalog_preparation_checkpoints (
                    library_item_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    video_id TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(library_item_id, fingerprint)
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def save(self, library_item_id: UUID, fingerprint: str, video_id: UUID) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO catalog_preparation_checkpoints (
                    library_item_id, fingerprint, video_id, updated_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(library_item_id, fingerprint) DO UPDATE SET
                    video_id = excluded.video_id,
                    updated_at = excluded.updated_at
                """,
                (
                    str(library_item_id),
                    fingerprint,
                    str(video_id),
                    utc_now().isoformat(),
                ),
            )

    def get_video_id(self, library_item_id: UUID, fingerprint: str) -> UUID | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT video_id FROM catalog_preparation_checkpoints
                WHERE library_item_id = ? AND fingerprint = ?
                """,
                (str(library_item_id), fingerprint),
            ).fetchone()
        return UUID(row[0]) if row is not None else None


class VideoChunkCheckpointStatus(str, Enum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class VideoChunkCheckpoint:
    video_id: UUID
    start_ms: int
    end_ms: int
    provider: str
    model: str
    chunk_duration_ms: int
    overlap_ms: int
    status: VideoChunkCheckpointStatus
    attempt_count: int
    last_error: str | None


class VideoChunkCheckpointStore:
    """Persists retry state independently for each video index profile and chunk."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = canonicalize_path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS catalog_video_chunk_checkpoints (
                    video_id TEXT NOT NULL,
                    start_ms INTEGER NOT NULL,
                    end_ms INTEGER NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    chunk_duration_ms INTEGER NOT NULL,
                    overlap_ms INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL,
                    last_error TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(
                        video_id, start_ms, end_ms, provider, model,
                        chunk_duration_ms, overlap_ms
                    )
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _parameters(
        video_id: UUID,
        start_ms: int,
        end_ms: int,
        provider: str,
        model: str,
        chunk_duration_ms: int,
        overlap_ms: int,
    ) -> tuple[str, int, int, str, str, int, int]:
        return (
            str(video_id),
            start_ms,
            end_ms,
            provider,
            model,
            chunk_duration_ms,
            overlap_ms,
        )

    def get(
        self,
        video_id: UUID,
        start_ms: int,
        end_ms: int,
        provider: str,
        model: str,
        *,
        chunk_duration_ms: int = DEFAULT_VIDEO_INDEX_PROFILE.chunk_duration_ms,
        overlap_ms: int = DEFAULT_VIDEO_INDEX_PROFILE.overlap_ms,
    ) -> VideoChunkCheckpoint | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM catalog_video_chunk_checkpoints
                WHERE video_id = ? AND start_ms = ? AND end_ms = ?
                    AND provider = ? AND model = ?
                    AND chunk_duration_ms = ? AND overlap_ms = ?
                """,
                self._parameters(
                    video_id,
                    start_ms,
                    end_ms,
                    provider,
                    model,
                    chunk_duration_ms,
                    overlap_ms,
                ),
            ).fetchone()
        if row is None:
            return None
        return VideoChunkCheckpoint(
            video_id=UUID(row["video_id"]),
            start_ms=row["start_ms"],
            end_ms=row["end_ms"],
            provider=row["provider"],
            model=row["model"],
            chunk_duration_ms=row["chunk_duration_ms"],
            overlap_ms=row["overlap_ms"],
            status=VideoChunkCheckpointStatus(row["status"]),
            attempt_count=row["attempt_count"],
            last_error=row["last_error"],
        )

    def is_completed(
        self,
        video_id: UUID,
        start_ms: int,
        end_ms: int,
        provider: str,
        model: str,
        *,
        chunk_duration_ms: int = DEFAULT_VIDEO_INDEX_PROFILE.chunk_duration_ms,
        overlap_ms: int = DEFAULT_VIDEO_INDEX_PROFILE.overlap_ms,
    ) -> bool:
        checkpoint = self.get(
            video_id,
            start_ms,
            end_ms,
            provider,
            model,
            chunk_duration_ms=chunk_duration_ms,
            overlap_ms=overlap_ms,
        )
        return checkpoint is not None and checkpoint.status is VideoChunkCheckpointStatus.COMPLETED

    def mark_processing(
        self,
        video_id: UUID,
        start_ms: int,
        end_ms: int,
        provider: str,
        model: str,
        *,
        chunk_duration_ms: int = DEFAULT_VIDEO_INDEX_PROFILE.chunk_duration_ms,
        overlap_ms: int = DEFAULT_VIDEO_INDEX_PROFILE.overlap_ms,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO catalog_video_chunk_checkpoints (
                    video_id, start_ms, end_ms, provider, model,
                    chunk_duration_ms, overlap_ms,
                    status, attempt_count, last_error, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, NULL, ?)
                ON CONFLICT(
                    video_id, start_ms, end_ms, provider, model,
                    chunk_duration_ms, overlap_ms
                ) DO UPDATE SET
                    status = excluded.status,
                    attempt_count = catalog_video_chunk_checkpoints.attempt_count + 1,
                    last_error = NULL,
                    updated_at = excluded.updated_at
                """,
                (
                    *self._parameters(
                        video_id,
                        start_ms,
                        end_ms,
                        provider,
                        model,
                        chunk_duration_ms,
                        overlap_ms,
                    ),
                    VideoChunkCheckpointStatus.PROCESSING.value,
                    utc_now().isoformat(),
                ),
            )

    def mark_completed(
        self,
        video_id: UUID,
        start_ms: int,
        end_ms: int,
        provider: str,
        model: str,
        *,
        chunk_duration_ms: int = DEFAULT_VIDEO_INDEX_PROFILE.chunk_duration_ms,
        overlap_ms: int = DEFAULT_VIDEO_INDEX_PROFILE.overlap_ms,
    ) -> None:
        self._mark_terminal(
            video_id,
            start_ms,
            end_ms,
            provider,
            model,
            chunk_duration_ms=chunk_duration_ms,
            overlap_ms=overlap_ms,
            status=VideoChunkCheckpointStatus.COMPLETED,
            error=None,
        )

    def mark_failed(
        self,
        video_id: UUID,
        start_ms: int,
        end_ms: int,
        provider: str,
        model: str,
        *,
        chunk_duration_ms: int = DEFAULT_VIDEO_INDEX_PROFILE.chunk_duration_ms,
        overlap_ms: int = DEFAULT_VIDEO_INDEX_PROFILE.overlap_ms,
        error: str,
    ) -> None:
        self._mark_terminal(
            video_id,
            start_ms,
            end_ms,
            provider,
            model,
            chunk_duration_ms=chunk_duration_ms,
            overlap_ms=overlap_ms,
            status=VideoChunkCheckpointStatus.FAILED,
            error=error,
        )

    def _mark_terminal(
        self,
        video_id: UUID,
        start_ms: int,
        end_ms: int,
        provider: str,
        model: str,
        *,
        chunk_duration_ms: int,
        overlap_ms: int,
        status: VideoChunkCheckpointStatus,
        error: str | None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO catalog_video_chunk_checkpoints (
                    video_id, start_ms, end_ms, provider, model,
                    chunk_duration_ms, overlap_ms,
                    status, attempt_count, last_error, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                ON CONFLICT(
                    video_id, start_ms, end_ms, provider, model,
                    chunk_duration_ms, overlap_ms
                ) DO UPDATE SET
                    status = excluded.status,
                    last_error = excluded.last_error,
                    updated_at = excluded.updated_at
                """,
                (
                    *self._parameters(
                        video_id,
                        start_ms,
                        end_ms,
                        provider,
                        model,
                        chunk_duration_ms,
                        overlap_ms,
                    ),
                    status.value,
                    error,
                    utc_now().isoformat(),
                ),
            )

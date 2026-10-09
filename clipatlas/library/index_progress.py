import math
import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, Field

from clipatlas.asr.audio import MAX_ASR_CHUNK_DURATION_MS
from clipatlas.library.fingerprint import canonicalize_path
from clipatlas.retrieval.video_profiles import DEFAULT_VIDEO_INDEX_PROFILE
from clipatlas.video.chunks import plan_video_chunks

_VISUAL_PROVIDER = "qwen-vl-video"
_VISUAL_MODEL = "qwen3-vl-embedding"
_ASR_PROVIDER = "bailian-asr"
_ASR_MODEL = "qwen-audio-3.0-asr-flash"
_OCR_PROVIDER = "bailian-ocr"
_OCR_MODEL = "qwen3.5-ocr"


class IndexSourceProgress(BaseModel):
    enabled: bool
    applicable: bool = True
    completed: int = Field(ge=0)
    processing: int = Field(ge=0)
    failed: int = Field(ge=0)
    total: int = Field(ge=0)


class VideoIndexProgress(BaseModel):
    visual: IndexSourceProgress
    asr: IndexSourceProgress
    ocr: IndexSourceProgress


class PreparedIndexProgress(BaseModel):
    video_id: UUID
    progress: VideoIndexProgress
    updated_at: datetime | None = None


class LibraryIndexProgressReader:
    """Read-only projection of existing visual/ASR/OCR checkpoint state."""

    def __init__(
        self,
        db_path: Path,
        *,
        visual_enabled: bool,
        asr_enabled: bool,
        ocr_interval_ms: int | None,
    ) -> None:
        if ocr_interval_ms is not None and ocr_interval_ms <= 0:
            raise ValueError("ocr_interval_ms must be positive when enabled")
        self._db_path = canonicalize_path(db_path)
        self._visual_enabled = visual_enabled
        self._asr_enabled = asr_enabled
        self._ocr_interval_ms = ocr_interval_ms

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path.as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        return connection

    def get_for_item(self, item_id: UUID, fingerprint: str) -> PreparedIndexProgress | None:
        """Expose current-version preparation before the worker marks the item completed."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT p.video_id FROM catalog_preparation_checkpoints p "
                "JOIN catalog_videos v ON v.id=p.video_id "
                "WHERE p.library_item_id=? AND p.fingerprint=?",
                (str(item_id), fingerprint),
            ).fetchone()
            if row is None:
                return None
            video_id = UUID(row["video_id"])
            latest = connection.execute(
                """
                SELECT MAX(updated_at) AS updated_at FROM (
                    SELECT updated_at FROM catalog_preparation_checkpoints
                    WHERE library_item_id=? AND fingerprint=?
                    UNION ALL SELECT updated_at FROM catalog_video_chunk_checkpoints
                    WHERE video_id=? AND provider=? AND model=?
                        AND chunk_duration_ms=? AND overlap_ms=?
                    UNION ALL SELECT updated_at FROM catalog_asr_chunks
                    WHERE video_id=? AND provider=? AND model=?
                    UNION ALL SELECT updated_at FROM catalog_ocr_samples
                    WHERE video_id=? AND provider=? AND model=? AND interval_ms=?
                )
                """,
                (str(item_id), fingerprint, str(video_id), _VISUAL_PROVIDER, _VISUAL_MODEL,
                 DEFAULT_VIDEO_INDEX_PROFILE.chunk_duration_ms,
                 DEFAULT_VIDEO_INDEX_PROFILE.overlap_ms,
                 str(video_id), _ASR_PROVIDER, _ASR_MODEL,
                 str(video_id), _OCR_PROVIDER, _OCR_MODEL, self._ocr_interval_ms),
            ).fetchone()
        try:
            progress = self.get(video_id)
        except KeyError:
            # A user-requested reset may remove preparation between these reads.
            return None
        return PreparedIndexProgress(
            video_id=video_id, progress=progress,
            updated_at=datetime.fromisoformat(latest["updated_at"]) if latest["updated_at"] else None,
        )

    @staticmethod
    def _empty(*, enabled: bool, applicable: bool = True) -> IndexSourceProgress:
        return IndexSourceProgress(
            enabled=enabled,
            applicable=applicable,
            completed=0,
            processing=0,
            failed=0,
            total=0,
        )

    @staticmethod
    def _counts(rows: list[sqlite3.Row], *, total: int) -> IndexSourceProgress:
        counts = {"completed": 0, "processing": 0, "failed": 0}
        for row in rows:
            status = str(row["status"])
            if status in counts:
                counts[status] += int(row["count"])
        return IndexSourceProgress(
            enabled=True,
            applicable=True,
            completed=counts["completed"],
            processing=counts["processing"],
            failed=counts["failed"],
            total=total,
        )

    def get(self, video_id: UUID) -> VideoIndexProgress:
        with self._connect() as connection:
            video = connection.execute(
                "SELECT duration_ms, has_audio FROM catalog_videos WHERE id = ?",
                (str(video_id),),
            ).fetchone()
            if video is None:
                raise KeyError(video_id)
            duration_ms = int(video["duration_ms"])
            has_audio = bool(video["has_audio"])

            visual = self._visual_progress(connection, video_id, duration_ms)
            asr = self._asr_progress(connection, video_id, duration_ms, has_audio)
            ocr = self._ocr_progress(connection, video_id, duration_ms)
        return VideoIndexProgress(visual=visual, asr=asr, ocr=ocr)

    def _visual_progress(
        self,
        connection: sqlite3.Connection,
        video_id: UUID,
        duration_ms: int,
    ) -> IndexSourceProgress:
        if not self._visual_enabled:
            return self._empty(enabled=False)
        profile = DEFAULT_VIDEO_INDEX_PROFILE
        total = len(
            plan_video_chunks(
                duration_ms,
                chunk_duration_ms=profile.chunk_duration_ms,
                overlap_ms=profile.overlap_ms,
            )
        )
        rows = connection.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM catalog_video_chunk_checkpoints
            WHERE video_id = ? AND provider = ? AND model = ?
                AND chunk_duration_ms = ? AND overlap_ms = ?
            GROUP BY status
            """,
            (
                str(video_id),
                _VISUAL_PROVIDER,
                _VISUAL_MODEL,
                profile.chunk_duration_ms,
                profile.overlap_ms,
            ),
        ).fetchall()
        return self._counts(rows, total=total)

    def _asr_progress(
        self,
        connection: sqlite3.Connection,
        video_id: UUID,
        duration_ms: int,
        has_audio: bool,
    ) -> IndexSourceProgress:
        if not self._asr_enabled:
            return self._empty(enabled=False)
        if not has_audio:
            return self._empty(enabled=True, applicable=False)
        total = math.ceil(duration_ms / MAX_ASR_CHUNK_DURATION_MS) if duration_ms else 0
        revision_row = connection.execute(
            """
            SELECT MAX(revision) AS revision
            FROM catalog_asr_chunks
            WHERE video_id = ? AND provider = ? AND model = ?
            """,
            (str(video_id), _ASR_PROVIDER, _ASR_MODEL),
        ).fetchone()
        revision = revision_row["revision"] if revision_row is not None else None
        if revision is None:
            return IndexSourceProgress(
                enabled=True, applicable=True,
                completed=0, processing=0, failed=0, total=total,
            )
        rows = connection.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM catalog_asr_chunks
            WHERE video_id = ? AND provider = ? AND model = ? AND revision = ?
            GROUP BY status
            """,
            (str(video_id), _ASR_PROVIDER, _ASR_MODEL, revision),
        ).fetchall()
        return self._counts(rows, total=total)

    def _ocr_progress(
        self,
        connection: sqlite3.Connection,
        video_id: UUID,
        duration_ms: int,
    ) -> IndexSourceProgress:
        interval_ms = self._ocr_interval_ms
        if interval_ms is None:
            return self._empty(enabled=False)
        total = math.ceil(duration_ms / interval_ms) if duration_ms else 0
        revision_row = connection.execute(
            """
            SELECT MAX(revision) AS revision
            FROM catalog_ocr_samples
            WHERE video_id = ? AND provider = ? AND model = ? AND interval_ms = ?
            """,
            (str(video_id), _OCR_PROVIDER, _OCR_MODEL, interval_ms),
        ).fetchone()
        revision = revision_row["revision"] if revision_row is not None else None
        if revision is None:
            return IndexSourceProgress(
                enabled=True, applicable=True,
                completed=0, processing=0, failed=0, total=total,
            )
        rows = connection.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM catalog_ocr_samples
            WHERE video_id = ? AND provider = ? AND model = ?
                AND interval_ms = ? AND revision = ?
            GROUP BY status
            """,
            (str(video_id), _OCR_PROVIDER, _OCR_MODEL, interval_ms, revision),
        ).fetchall()
        return self._counts(rows, total=total)

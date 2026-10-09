import json
import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import UUID

from clipatlas.asr.models import (
    ASRChunkRecord,
    ASRChunkStatus,
    ASRSentence,
    ASRTextMatch,
)
from clipatlas.library.fingerprint import canonicalize_path


def normalize_asr_text(text: str) -> str:
    return " ".join(text.split()).casefold()


class ASRStore:
    """ASR persistence backed by the existing ClipAtlas library SQLite file."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = canonicalize_path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS catalog_asr_chunks (
                    video_id TEXT NOT NULL,
                    start_ms INTEGER NOT NULL,
                    end_ms INTEGER NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL,
                    last_error TEXT,
                    sentences_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (
                        video_id, start_ms, end_ms, provider, model, revision
                    )
                );

                CREATE INDEX IF NOT EXISTS idx_catalog_asr_chunks_lookup
                ON catalog_asr_chunks(video_id, provider, model, revision, start_ms);
                """
            )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> ASRChunkRecord:
        return ASRChunkRecord(
            video_id=UUID(row["video_id"]),
            start_ms=row["start_ms"],
            end_ms=row["end_ms"],
            provider=row["provider"],
            model=row["model"],
            revision=row["revision"],
            status=ASRChunkStatus(row["status"]),
            attempt_count=row["attempt_count"],
            last_error=row["last_error"],
            sentences=[
                ASRSentence.model_validate(item)
                for item in json.loads(row["sentences_json"])
            ],
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def save_asr_chunk(self, record: ASRChunkRecord) -> None:
        sentences_json = json.dumps(
            [sentence.model_dump(mode="json") for sentence in record.sentences],
            ensure_ascii=False,
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO catalog_asr_chunks (
                    video_id, start_ms, end_ms, provider, model, revision,
                    status, attempt_count, last_error, sentences_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(
                    video_id, start_ms, end_ms, provider, model, revision
                ) DO UPDATE SET
                    status = excluded.status,
                    attempt_count = excluded.attempt_count,
                    last_error = excluded.last_error,
                    sentences_json = excluded.sentences_json,
                    updated_at = excluded.updated_at
                """,
                (
                    str(record.video_id),
                    record.start_ms,
                    record.end_ms,
                    record.provider,
                    record.model,
                    record.revision,
                    record.status.value,
                    record.attempt_count,
                    record.last_error,
                    sentences_json,
                    record.updated_at.isoformat(),
                ),
            )

    def get_asr_chunk(
        self,
        video_id: UUID,
        start_ms: int,
        end_ms: int,
        provider: str,
        model: str,
        *,
        revision: int,
    ) -> ASRChunkRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM catalog_asr_chunks
                WHERE video_id = ? AND start_ms = ? AND end_ms = ?
                    AND provider = ? AND model = ? AND revision = ?
                LIMIT 1
                """,
                (str(video_id), start_ms, end_ms, provider, model, revision),
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def get_latest_asr_revision(
        self,
        video_id: UUID,
        provider: str,
        model: str,
    ) -> int | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT MAX(revision) AS revision
                FROM catalog_asr_chunks
                WHERE video_id = ? AND provider = ? AND model = ?
                """,
                (str(video_id), provider, model),
            ).fetchone()
        if row is None or row["revision"] is None:
            return None
        return int(row["revision"])

    def list_asr_chunks(
        self,
        video_id: UUID,
        provider: str | None = None,
        model: str | None = None,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ASRChunkRecord]:
        if (limit is not None and limit < 1) or offset < 0:
            raise ValueError("invalid pagination")
        query = "SELECT rowid, * FROM catalog_asr_chunks WHERE video_id = ?"
        parameters: list[object] = [str(video_id)]
        for column, value in (("provider", provider), ("model", model)):
            if value is not None:
                query += f" AND {column} = ?"
                parameters.append(value)
        query += " ORDER BY revision, start_ms, end_ms, rowid"
        if limit is not None or offset:
            query += " LIMIT ? OFFSET ?"
            parameters.extend((limit if limit is not None else -1, offset))
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._from_row(row) for row in rows]

    def search_text(
        self,
        query: str,
        provider: str,
        model: str,
        *,
        limit: int,
        video_ids: list[UUID] | None = None,
    ) -> list[ASRTextMatch]:
        normalized_query = normalize_asr_text(query)
        if not normalized_query or limit <= 0:
            return []
        if video_ids is not None and not video_ids:
            return []

        conditions = ["provider = ?", "model = ?", "status = ?"]
        parameters: list[object] = [provider, model, ASRChunkStatus.COMPLETED.value]
        if video_ids is not None:
            placeholders = ", ".join("?" for _ in video_ids)
            conditions.append(f"video_id IN ({placeholders})")
            parameters.extend(str(video_id) for video_id in video_ids)

        where_clause = " AND ".join(conditions)
        sql = f"""
            WITH ranked AS (
                SELECT
                    rowid AS source_rowid,
                    *,
                    ROW_NUMBER() OVER (
                        PARTITION BY video_id, start_ms, end_ms, provider, model
                        ORDER BY revision DESC, rowid DESC
                    ) AS rn
                FROM catalog_asr_chunks
                WHERE {where_clause}
            )
            SELECT * FROM ranked
            WHERE rn = 1 AND instr(lower(sentences_json), lower(?)) > 0
            ORDER BY video_id, start_ms, end_ms, source_rowid
        """
        parameters.append(normalized_query)

        with self._connect() as connection:
            rows = connection.execute(sql, parameters).fetchall()

        matches: list[ASRTextMatch] = []
        for row in rows:
            record = self._from_row(row)
            for sentence in record.sentences:
                if normalized_query not in normalize_asr_text(sentence.text):
                    continue
                matches.append(
                    ASRTextMatch(
                        video_id=record.video_id,
                        start_ms=sentence.start_ms,
                        end_ms=sentence.end_ms,
                        text=sentence.text,
                        revision=record.revision,
                    )
                )
                if len(matches) >= limit:
                    return matches
        return matches

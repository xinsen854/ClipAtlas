import sqlite3
from pathlib import Path
from uuid import UUID

from finecut.models import TimelineDocument


class TimelineStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path.expanduser().resolve()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS timeline_documents (
                    project_id TEXT NOT NULL,
                    source_plan_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY (project_id, source_plan_id)
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def save(self, document: TimelineDocument) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO timeline_documents (project_id, source_plan_id, payload_json)
                VALUES (?, ?, ?)
                ON CONFLICT(project_id, source_plan_id) DO UPDATE SET
                    payload_json = excluded.payload_json
                """,
                (
                    str(document.project_id),
                    str(document.source_plan_id),
                    document.model_dump_json(),
                ),
            )

    def get(self, project_id: UUID, source_plan_id: UUID) -> TimelineDocument | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM timeline_documents
                WHERE project_id = ? AND source_plan_id = ?
                """,
                (str(project_id), str(source_plan_id)),
            ).fetchone()
        return TimelineDocument.model_validate_json(row[0]) if row is not None else None

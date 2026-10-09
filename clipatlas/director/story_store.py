import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import UUID

from clipatlas.director.story_models import StoryOutline
from clipatlas.domain.models import utc_now
from clipatlas.library.fingerprint import canonicalize_path


class StoryOutlineStore:
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
                CREATE TABLE IF NOT EXISTS auto_director_outlines (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    outline_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    confirmed_at TEXT,
                    UNIQUE(project_id, revision)
                );
                CREATE INDEX IF NOT EXISTS idx_auto_director_project_revision
                ON auto_director_outlines(project_id, revision DESC);
                """
            )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> StoryOutline:
        return StoryOutline.model_validate_json(row["outline_json"])

    def next_revision(self, project_id: UUID) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT MAX(revision) AS revision FROM auto_director_outlines WHERE project_id=?",
                (str(project_id),),
            ).fetchone()
        if row is None or row["revision"] is None:
            return 1
        return int(row["revision"]) + 1

    def save(self, outline: StoryOutline) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO auto_director_outlines (
                    id, project_id, revision, status, outline_json, created_at, confirmed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(outline.id),
                    str(outline.project_id),
                    outline.revision,
                    outline.status,
                    outline.model_dump_json(),
                    outline.created_at.isoformat(),
                    outline.confirmed_at.isoformat() if outline.confirmed_at else None,
                ),
            )

    def get(self, outline_id: UUID) -> StoryOutline | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT outline_json FROM auto_director_outlines WHERE id=?",
                (str(outline_id),),
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def list_project(self, project_id: UUID) -> list[StoryOutline]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT outline_json FROM auto_director_outlines
                WHERE project_id=? ORDER BY revision DESC, created_at DESC
                """,
                (str(project_id),),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def confirm(self, outline_id: UUID) -> StoryOutline | None:
        outline = self.get(outline_id)
        if outline is None:
            return None
        confirmed = outline.model_copy(
            update={"status": "confirmed", "confirmed_at": utc_now()},
            deep=True,
        )
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE auto_director_outlines
                SET status=?, outline_json=?, confirmed_at=?
                WHERE id=?
                """,
                (
                    confirmed.status,
                    confirmed.model_dump_json(),
                    confirmed.confirmed_at.isoformat() if confirmed.confirmed_at else None,
                    str(outline_id),
                ),
            )
        return confirmed

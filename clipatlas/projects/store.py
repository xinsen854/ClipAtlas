import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import UUID

from clipatlas.domain.models import utc_now
from clipatlas.library.fingerprint import canonicalize_path
from clipatlas.projects.models import Project


class ProjectStore:
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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Project:
        return Project(
            id=UUID(row["id"]),
            name=row["name"],
            description=row["description"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def create(self, name: str, description: str | None = None) -> Project:
        project = Project(name=name, description=description)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO projects (id, name, description, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(project.id),
                    project.name,
                    project.description,
                    project.created_at.isoformat(),
                    project.updated_at.isoformat(),
                ),
            )
        return project

    def list_projects(self) -> list[Project]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM projects
                ORDER BY updated_at DESC, created_at DESC, id
                """
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def get(self, project_id: UUID) -> Project | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM projects WHERE id = ?",
                (str(project_id),),
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def update(
        self,
        project_id: UUID,
        *,
        name: str | None,
        description: str | None,
        description_set: bool,
    ) -> Project | None:
        current = self.get(project_id)
        if current is None:
            return None

        updated = Project(
            id=current.id,
            name=name if name is not None else current.name,
            description=description if description_set else current.description,
            created_at=current.created_at,
            updated_at=utc_now(),
        )
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE projects
                SET name = ?, description = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    updated.name,
                    updated.description,
                    updated.updated_at.isoformat(),
                    str(project_id),
                ),
            )
        return updated

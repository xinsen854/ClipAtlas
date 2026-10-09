import sqlite3
from pathlib import Path
from uuid import UUID

from clipatlas.library.fingerprint import canonicalize_path
from clipatlas.roughcut.models import RoughCutPlan


class RoughCutStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = canonicalize_path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS rough_cut_plans (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_rough_cut_plans_project_revision
                ON rough_cut_plans(project_id, revision DESC, created_at DESC);

                CREATE TABLE IF NOT EXISTS active_rough_cut_plans (
                    project_id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL,
                    FOREIGN KEY(plan_id) REFERENCES rough_cut_plans(id)
                );
                """
            )

    def save_plan(self, plan: RoughCutPlan) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO rough_cut_plans (
                    id, project_id, revision, created_at, payload_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(plan.id),
                    str(plan.project_id),
                    plan.revision,
                    plan.created_at.isoformat(),
                    plan.model_dump_json(),
                ),
            )

    def get_plan(self, plan_id: UUID) -> RoughCutPlan | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM rough_cut_plans WHERE id = ?",
                (str(plan_id),),
            ).fetchone()
        return RoughCutPlan.model_validate_json(row["payload_json"]) if row is not None else None

    def list_plans(self, project_id: UUID) -> list[RoughCutPlan]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload_json FROM rough_cut_plans
                WHERE project_id = ?
                ORDER BY revision DESC, created_at DESC, rowid DESC
                """,
                (str(project_id),),
            ).fetchall()
        return [RoughCutPlan.model_validate_json(row["payload_json"]) for row in rows]

    def next_plan_revision(self, project_id: UUID) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT MAX(revision) AS revision FROM rough_cut_plans WHERE project_id = ?",
                (str(project_id),),
            ).fetchone()
        current = row["revision"] if row is not None else None
        return int(current or 0) + 1

    def activate_plan(self, project_id: UUID, plan_id: UUID) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT project_id FROM rough_cut_plans WHERE id = ?",
                (str(plan_id),),
            ).fetchone()
            if row is None or row["project_id"] != str(project_id):
                return False

            connection.execute(
                """
                INSERT INTO active_rough_cut_plans (project_id, plan_id)
                VALUES (?, ?)
                ON CONFLICT(project_id) DO UPDATE SET plan_id = excluded.plan_id
                """,
                (str(project_id), str(plan_id)),
            )
        return True

    def get_active_plan(self, project_id: UUID) -> RoughCutPlan | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT p.payload_json
                FROM active_rough_cut_plans AS a
                JOIN rough_cut_plans AS p ON p.id = a.plan_id
                WHERE a.project_id = ?
                """,
                (str(project_id),),
            ).fetchone()
        return RoughCutPlan.model_validate_json(row["payload_json"]) if row is not None else None

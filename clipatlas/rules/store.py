import json
import sqlite3
from pathlib import Path
from uuid import UUID

from clipatlas.rules.models import ProjectRule, ProjectRulePack, RulePackStatus


class ProjectRuleStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path.expanduser().resolve(strict=False)
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
                CREATE TABLE IF NOT EXISTS project_rule_packs (
                    project_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    rules_json TEXT NOT NULL,
                    PRIMARY KEY (project_id, revision)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_project_rule_packs_active
                ON project_rule_packs (project_id, status, revision)
                """
            )

    @staticmethod
    def _rules_json(rules: list[ProjectRule]) -> str:
        return json.dumps(
            [rule.model_dump(mode="json") for rule in rules],
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> ProjectRulePack:
        raw_rules = json.loads(row["rules_json"])
        return ProjectRulePack(
            project_id=UUID(row["project_id"]),
            revision=int(row["revision"]),
            status=RulePackStatus(row["status"]),
            rules=[ProjectRule.model_validate(item) for item in raw_rules],
        )

    def save_draft(
        self,
        project_id: UUID,
        rules: list[ProjectRule],
    ) -> ProjectRulePack:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(MAX(revision), 0) AS max_revision
                FROM project_rule_packs
                WHERE project_id = ?
                """,
                (str(project_id),),
            ).fetchone()
            revision = int(row["max_revision"]) + 1
            pack = ProjectRulePack(
                project_id=project_id,
                revision=revision,
                status=RulePackStatus.DRAFT,
                rules=rules,
            )
            connection.execute(
                """
                INSERT INTO project_rule_packs (
                    project_id,
                    revision,
                    status,
                    rules_json
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    str(pack.project_id),
                    pack.revision,
                    pack.status.value,
                    self._rules_json(pack.rules),
                ),
            )
        return pack

    def list_revisions(self, project_id: UUID) -> list[ProjectRulePack]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT project_id, revision, status, rules_json
                FROM project_rule_packs
                WHERE project_id = ?
                ORDER BY revision DESC
                """,
                (str(project_id),),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def get_by_revision(
        self, project_id: UUID, revision: int,
    ) -> ProjectRulePack | None:
        """Read the rule pack at a locked revision (subtitle/narration binding)."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT project_id, revision, status, rules_json
                FROM project_rule_packs
                WHERE project_id = ? AND revision = ?
                LIMIT 1
                """,
                (str(project_id), int(revision)),
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def get_active(self, project_id: UUID) -> ProjectRulePack | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT project_id, revision, status, rules_json
                FROM project_rule_packs
                WHERE project_id = ? AND status = ?
                ORDER BY revision DESC
                LIMIT 1
                """,
                (str(project_id), RulePackStatus.ACTIVE.value),
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def activate(
        self,
        project_id: UUID,
        revision: int,
    ) -> ProjectRulePack | None:
        with self._connect() as connection:
            target = connection.execute(
                """
                SELECT project_id, revision, status, rules_json
                FROM project_rule_packs
                WHERE project_id = ? AND revision = ?
                """,
                (str(project_id), revision),
            ).fetchone()
            if target is None:
                return None

            connection.execute(
                """
                UPDATE project_rule_packs
                SET status = ?
                WHERE project_id = ?
                """,
                (RulePackStatus.DRAFT.value, str(project_id)),
            )
            connection.execute(
                """
                UPDATE project_rule_packs
                SET status = ?
                WHERE project_id = ? AND revision = ?
                """,
                (RulePackStatus.ACTIVE.value, str(project_id), revision),
            )
            row = connection.execute(
                """
                SELECT project_id, revision, status, rules_json
                FROM project_rule_packs
                WHERE project_id = ? AND revision = ?
                """,
                (str(project_id), revision),
            ).fetchone()
        return self._from_row(row) if row is not None else None

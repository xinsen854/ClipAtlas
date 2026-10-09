"""Permanent director-analysis cache.

Keyed by (script hash, prompt version, rules revision): an unchanged script
never calls the API again, even after re-planning or re-export.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from clipatlas.director.models import DirectorAnalysis
from clipatlas.library.fingerprint import canonicalize_path


class DirectorCacheStore:
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
                CREATE TABLE IF NOT EXISTS director_analyses (
                    script_hash TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    rules_revision TEXT NOT NULL,
                    analysis_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (script_hash, prompt_version, rules_revision)
                );
                """
            )

    def get(self, analysis: DirectorAnalysis) -> DirectorAnalysis | None:
        row = self._fetch(
            analysis.script_hash,
            analysis.prompt_version,
            analysis.rules_revision,
        )
        if row is None:
            return None
        return DirectorAnalysis.model_validate_json(row["analysis_json"])

    def get_by_key(self, script_hash: str, prompt_version: str, rules_revision: str) -> DirectorAnalysis | None:
        row = self._fetch(script_hash, prompt_version, rules_revision)
        if row is None:
            return None
        return DirectorAnalysis.model_validate_json(row["analysis_json"])

    def _fetch(self, script_hash: str, prompt_version: str, rules_revision: str) -> sqlite3.Row | None:
        with self._connect() as connection:
            return connection.execute(
                """
                SELECT analysis_json FROM director_analyses
                WHERE script_hash = ? AND prompt_version = ? AND rules_revision = ?
                """,
                (script_hash, prompt_version, rules_revision),
            ).fetchone()

    def put(self, analysis: DirectorAnalysis) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO director_analyses
                    (script_hash, prompt_version, rules_revision, analysis_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    analysis.script_hash,
                    analysis.prompt_version,
                    analysis.rules_revision,
                    analysis.model_dump_json(),
                    analysis.created_at.isoformat(),
                ),
            )

    def count(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS n FROM director_analyses").fetchone()
        return int(row["n"]) if row else 0

    def get_previous_version(self, script_hash: str, rules_revision: str) -> DirectorAnalysis | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT analysis_json FROM director_analyses WHERE script_hash=? AND rules_revision=? "
                "ORDER BY created_at DESC LIMIT 1", (script_hash, rules_revision),
            ).fetchone()
        return DirectorAnalysis.model_validate_json(row["analysis_json"]) if row else None

import sqlite3
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from uuid import UUID

from clipatlas.domain.models import utc_now
from clipatlas.library.fingerprint import canonicalize_path
from clipatlas.library.models import LibraryItem, LibraryItemStatus, LibraryRoot
from clipatlas.projects.models import Project

_INFLIGHT_STATUSES = (
    LibraryItemStatus.PROBING,
    LibraryItemStatus.SCENE_DETECTION,
    LibraryItemStatus.FRAME_EXTRACTION,
)


class LibraryStore:
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
                CREATE TABLE IF NOT EXISTS library_roots (
                    id TEXT PRIMARY KEY,
                    path TEXT NOT NULL UNIQUE,
                    recursive INTEGER NOT NULL,
                    enabled INTEGER NOT NULL,
                    project_id TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS library_items (
                    id TEXT PRIMARY KEY,
                    root_id TEXT NOT NULL,
                    source_path TEXT NOT NULL UNIQUE,
                    size_bytes INTEGER NOT NULL,
                    mtime_ns INTEGER NOT NULL,
                    fingerprint TEXT NOT NULL,
                    processed_fingerprint TEXT,
                    status TEXT NOT NULL,
                    video_id TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(root_id) REFERENCES library_roots(id)
                );

                CREATE INDEX IF NOT EXISTS idx_library_items_status_created
                ON library_items(status, created_at);

                CREATE TABLE IF NOT EXISTS library_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            try:
                connection.execute(
                    "ALTER TABLE library_roots ADD COLUMN project_id TEXT"
                )
            except sqlite3.OperationalError:
                pass  # 列已存在（新库或已迁移）

    @staticmethod
    def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
        return connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone() is not None

    @classmethod
    def _assign_root_project(
        cls, connection: sqlite3.Connection, root_id: str, project_id: UUID,
    ) -> None:
        project_text = str(project_id)
        connection.execute(
            "UPDATE library_roots SET project_id=? WHERE id=? AND project_id IS NULL",
            (project_text, root_id),
        )
        if not cls._table_exists(connection, "catalog_videos"):
            return
        connection.execute(
            "UPDATE catalog_videos SET project_id=? WHERE project_id IS NULL AND id IN ("
            "SELECT video_id FROM library_items WHERE root_id=? AND video_id IS NOT NULL)",
            (project_text, root_id),
        )
        if cls._table_exists(connection, "catalog_preparation_checkpoints"):
            connection.execute(
                "UPDATE catalog_videos SET project_id=? WHERE project_id IS NULL AND id IN ("
                "SELECT c.video_id FROM catalog_preparation_checkpoints c "
                "JOIN library_items i ON i.id=c.library_item_id WHERE i.root_id=?)",
                (project_text, root_id),
            )

    def migrate_legacy_project_ownership(self, projects: Sequence[Project]) -> int:
        """Keep legacy ownership unknown until a root is explicitly claimed.

        Creation times cannot establish ownership. Keep this startup hook for
        compatibility; explicit add_root(project_id=...) performs the claim.
        """
        return 0

    @staticmethod
    def _root_from_row(row: sqlite3.Row) -> LibraryRoot:
        keys = row.keys()
        raw_project = row["project_id"] if "project_id" in keys else None
        return LibraryRoot(
            id=UUID(row["id"]),
            path=row["path"],
            recursive=bool(row["recursive"]),
            enabled=bool(row["enabled"]),
            project_id=UUID(raw_project) if raw_project else None,
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    @staticmethod
    def _item_from_row(row: sqlite3.Row) -> LibraryItem:
        video_id = row["video_id"]
        return LibraryItem(
            id=UUID(row["id"]),
            root_id=UUID(row["root_id"]),
            source_path=row["source_path"],
            size_bytes=row["size_bytes"],
            mtime_ns=row["mtime_ns"],
            fingerprint=row["fingerprint"],
            processed_fingerprint=row["processed_fingerprint"],
            status=LibraryItemStatus(row["status"]),
            video_id=UUID(video_id) if video_id else None,
            attempts=row["attempts"],
            last_error=row["last_error"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def add_root(
        self,
        path: Path,
        recursive: bool = True,
        project_id: UUID | None = None,
    ) -> LibraryRoot:
        canonical = canonicalize_path(path)
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT * FROM library_roots WHERE path = ?",
                (str(canonical),),
            ).fetchone()
            if existing is not None:
                # 旧遗留根（project_id 为空）在某项目下重新添加时回填归属。
                legacy = existing["project_id"] if "project_id" in existing.keys() else None
                if project_id is not None and not legacy:
                    self._assign_root_project(connection, existing["id"], project_id)
                    existing = connection.execute(
                        "SELECT * FROM library_roots WHERE id = ?",
                        (existing["id"],),
                    ).fetchone()
                return self._root_from_row(existing)

            root = LibraryRoot(
                path=str(canonical), recursive=recursive, project_id=project_id,
            )
            connection.execute(
                """
                INSERT INTO library_roots (id, path, recursive, enabled, project_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(root.id),
                    root.path,
                    int(root.recursive),
                    int(root.enabled),
                    str(root.project_id) if root.project_id else None,
                    root.created_at.isoformat(),
                ),
            )
            return root

    def get_root(self, root_id: UUID) -> LibraryRoot | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM library_roots WHERE id = ?",
                (str(root_id),),
            ).fetchone()
        return self._root_from_row(row) if row is not None else None

    def list_roots(
        self,
        enabled_only: bool = False,
        project_id: UUID | None = None,
    ) -> list[LibraryRoot]:
        clauses: list[str] = []
        parameters: list[object] = []
        if enabled_only:
            clauses.append("enabled = ?")
            parameters.append(1)
        if project_id is not None:
            clauses.append("project_id = ?")
            parameters.append(str(project_id))
        query = "SELECT * FROM library_roots"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at, id"
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._root_from_row(row) for row in rows]

    def get_item_by_path(self, source_path: Path) -> LibraryItem | None:
        canonical = canonicalize_path(source_path)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM library_items WHERE source_path = ?",
                (str(canonical),),
            ).fetchone()
        return self._item_from_row(row) if row is not None else None

    def get_item(self, item_id: UUID) -> LibraryItem | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM library_items WHERE id = ?",
                (str(item_id),),
            ).fetchone()
        return self._item_from_row(row) if row is not None else None

    def list_items(
        self,
        root_id: UUID | None = None,
        status: LibraryItemStatus | None = None,
        limit: int = 100,
        offset: int = 0,
        project_id: UUID | None = None,
    ) -> list[LibraryItem]:
        if limit < 1:
            raise ValueError("limit must be positive")
        if offset < 0:
            raise ValueError("offset must be non-negative")

        conditions: list[str] = []
        parameters: list[object] = []
        join_clause = ""
        if project_id is not None:
            # 通过素材根归属严格过滤项目；未分配遗留根不会泄漏到新项目。
            join_clause = (
                " JOIN library_roots r ON r.id = library_items.root_id"
            )
            conditions.append("r.project_id = ?")
            parameters.append(str(project_id))
        if root_id is not None:
            conditions.append("library_items.root_id = ?")
            parameters.append(str(root_id))
        if status is not None:
            conditions.append("library_items.status = ?")
            parameters.append(status.value)

        query = "SELECT library_items.* FROM library_items" + join_clause
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY library_items.created_at, library_items.id LIMIT ? OFFSET ?"
        parameters.extend((limit, offset))

        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._item_from_row(row) for row in rows]

    def save_observation(
        self,
        root_id: UUID,
        source_path: Path,
        size_bytes: int,
        mtime_ns: int,
        fingerprint: str,
    ) -> str:
        canonical = canonicalize_path(source_path)
        now = utc_now()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM library_items WHERE source_path = ?",
                (str(canonical),),
            ).fetchone()

            if row is None:
                item = LibraryItem(
                    root_id=root_id,
                    source_path=str(canonical),
                    size_bytes=size_bytes,
                    mtime_ns=mtime_ns,
                    fingerprint=fingerprint,
                    created_at=now,
                    updated_at=now,
                )
                connection.execute(
                    """
                    INSERT INTO library_items (
                        id, root_id, source_path, size_bytes, mtime_ns, fingerprint,
                        processed_fingerprint, status, video_id, attempts, last_error,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(item.id),
                        str(item.root_id),
                        item.source_path,
                        item.size_bytes,
                        item.mtime_ns,
                        item.fingerprint,
                        item.processed_fingerprint,
                        item.status.value,
                        None,
                        item.attempts,
                        item.last_error,
                        item.created_at.isoformat(),
                        item.updated_at.isoformat(),
                    ),
                )
                return "discovered"

            current = self._item_from_row(row)
            if current.fingerprint != fingerprint:
                connection.execute(
                    """
                    UPDATE library_items
                    SET root_id = ?, size_bytes = ?, mtime_ns = ?, fingerprint = ?,
                        processed_fingerprint = NULL, status = ?, video_id = NULL,
                        last_error = NULL, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        str(root_id),
                        size_bytes,
                        mtime_ns,
                        fingerprint,
                        LibraryItemStatus.QUEUED.value,
                        now.isoformat(),
                        str(current.id),
                    ),
                )
                return "changed"

            if current.status is LibraryItemStatus.MISSING:
                restored_status = (
                    LibraryItemStatus.COMPLETED
                    if current.processed_fingerprint == fingerprint and current.video_id is not None
                    else LibraryItemStatus.QUEUED
                )
                connection.execute(
                    """
                    UPDATE library_items
                    SET root_id = ?, size_bytes = ?, mtime_ns = ?, status = ?,
                        last_error = NULL, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        str(root_id),
                        size_bytes,
                        mtime_ns,
                        restored_status.value,
                        now.isoformat(),
                        str(current.id),
                    ),
                )
                return "restored"

            return "unchanged"

    def mark_missing(self, item_id: UUID) -> None:
        self.set_status(item_id, LibraryItemStatus.MISSING)

    def claim_next(self) -> LibraryItem | None:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM library_items
                WHERE status = ?
                ORDER BY created_at, id
                LIMIT 1
                """,
                (LibraryItemStatus.QUEUED.value,),
            ).fetchone()
            if row is None:
                connection.commit()
                return None

            item_id = row["id"]
            connection.execute(
                """
                UPDATE library_items
                SET status = ?, attempts = attempts + 1, updated_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    LibraryItemStatus.PROBING.value,
                    utc_now().isoformat(),
                    item_id,
                    LibraryItemStatus.QUEUED.value,
                ),
            )
            claimed_row = connection.execute(
                "SELECT * FROM library_items WHERE id = ?",
                (item_id,),
            ).fetchone()
            connection.commit()
            if claimed_row is None:
                return None
            return self._item_from_row(claimed_row)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def claim_item(self, item_id: UUID) -> LibraryItem | None:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE library_items
                SET status = ?, attempts = attempts + 1, updated_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    LibraryItemStatus.PROBING.value,
                    utc_now().isoformat(),
                    str(item_id),
                    LibraryItemStatus.QUEUED.value,
                ),
            )
            if cursor.rowcount != 1:
                connection.commit()
                return None
            claimed_row = connection.execute(
                "SELECT * FROM library_items WHERE id = ?",
                (str(item_id),),
            ).fetchone()
            connection.commit()
            if claimed_row is None:
                return None
            return self._item_from_row(claimed_row)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def claim_item_for_reparse(self, item_id: UUID) -> LibraryItem | None:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE library_items
                SET status = ?, attempts = attempts + 1, last_error = NULL, updated_at = ?
                WHERE id = ? AND status IN (?, ?, ?)
                """,
                (
                    LibraryItemStatus.PROBING.value,
                    utc_now().isoformat(),
                    str(item_id),
                    LibraryItemStatus.COMPLETED.value,
                    LibraryItemStatus.FAILED.value,
                    LibraryItemStatus.QUEUED.value,
                ),
            )
            if cursor.rowcount != 1:
                connection.commit()
                return None
            claimed_row = connection.execute(
                "SELECT * FROM library_items WHERE id = ?",
                (str(item_id),),
            ).fetchone()
            connection.commit()
            if claimed_row is None:
                return None
            return self._item_from_row(claimed_row)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def set_status(self, item_id: UUID, status: LibraryItemStatus) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE library_items SET status = ?, updated_at = ? WHERE id = ?",
                (status.value, utc_now().isoformat(), str(item_id)),
            )

    def complete(self, item_id: UUID, video_id: UUID) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE library_items
                SET status = ?, video_id = ?, processed_fingerprint = fingerprint,
                    last_error = NULL, updated_at = ?
                WHERE id = ?
                """,
                (
                    LibraryItemStatus.COMPLETED.value,
                    str(video_id),
                    utc_now().isoformat(),
                    str(item_id),
                ),
            )

    def fail(self, item_id: UUID, error: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE library_items
                SET status = ?, last_error = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    LibraryItemStatus.FAILED.value,
                    error[:2000],
                    utc_now().isoformat(),
                    str(item_id),
                ),
            )

    def retry(self, item_id: UUID) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE library_items
                SET status = ?, last_error = NULL, updated_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    LibraryItemStatus.QUEUED.value,
                    utc_now().isoformat(),
                    str(item_id),
                    LibraryItemStatus.FAILED.value,
                ),
            )
            return cursor.rowcount == 1

    def requeue_completed(self, item_id: UUID) -> bool:
        """Put a completed item back in the queue for an incremental pass.

        The non-force worker path skips whatever is already indexed, so this
        only fills gaps (OCR/ASR/annotation/media-type) without redoing work.
        """
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE library_items
                SET status = ?, updated_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    LibraryItemStatus.QUEUED.value,
                    utc_now().isoformat(),
                    str(item_id),
                    LibraryItemStatus.COMPLETED.value,
                ),
            )
            return cursor.rowcount == 1

    def recover_interrupted(self) -> int:
        placeholders = ", ".join("?" for _ in _INFLIGHT_STATUSES)
        with self._connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE library_items
                SET status = ?, updated_at = ?
                WHERE status IN ({placeholders})
                """,
                (
                    LibraryItemStatus.QUEUED.value,
                    utc_now().isoformat(),
                    *(status.value for status in _INFLIGHT_STATUSES),
                ),
            )
            return cursor.rowcount

    def counts_by_status(
        self, project_id: UUID | None = None,
    ) -> dict[LibraryItemStatus, int]:
        counts = {status: 0 for status in LibraryItemStatus}
        with self._connect() as connection:
            if project_id is not None:
                rows = connection.execute(
                    "SELECT i.status AS status, COUNT(*) AS count "
                    "FROM library_items i JOIN library_roots r ON r.id = i.root_id "
                    "WHERE r.project_id = ? GROUP BY i.status",
                    (str(project_id),),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT status, COUNT(*) AS count FROM library_items GROUP BY status"
                ).fetchall()
        for row in rows:
            counts[LibraryItemStatus(row["status"])] = row["count"]
        return counts

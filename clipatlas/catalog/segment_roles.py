"""Sparse per-segment fallback roles for rough-cut b-roll.

Video-level ``fallback_role`` remains useful for dedicated b-roll folders. This
store adds the finer control requested by editors: a single good empty shot or
neutral detail inside an otherwise normal source video can be explicitly
marked ``generic`` without reclassifying the whole video. ``review_placeholder``
is an even narrower last-resort role: it is a pre-approved clean local segment
used only when normal legal footage and generic/source fallbacks are exhausted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from clipatlas.catalog.store import CatalogStore

SegmentFallbackRole = Literal["normal", "generic", "review_placeholder", "never"]
SelectableFallbackRole = Literal["generic", "review_placeholder", "never"]
_ALLOWED = frozenset({"normal", "generic", "review_placeholder", "never"})


@dataclass(frozen=True, slots=True)
class SegmentFallbackRange:
    segment_id: UUID
    video_id: UUID
    start_ms: int
    end_ms: int


class SegmentFallbackRoleStore:
    def __init__(self, catalog: CatalogStore) -> None:
        self._catalog = catalog
        self._initialize()

    def _initialize(self) -> None:
        with self._catalog._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS catalog_segment_fallback_roles (
                    segment_id TEXT PRIMARY KEY,
                    role TEXT NOT NULL,
                    FOREIGN KEY(segment_id) REFERENCES catalog_segments(id)
                );
                CREATE INDEX IF NOT EXISTS idx_segment_fallback_roles_role
                ON catalog_segment_fallback_roles(role, segment_id);
                """
            )

    def set_role(self, segment_id: UUID, role: SegmentFallbackRole) -> None:
        if role not in _ALLOWED:
            raise ValueError(
                "segment fallback role must be normal, generic, review_placeholder, or never"
            )
        with self._catalog._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM catalog_segments WHERE id = ?", (str(segment_id),)
            ).fetchone()
            if exists is None:
                raise KeyError(f"unknown segment: {segment_id}")
            if role == "normal":
                connection.execute(
                    "DELETE FROM catalog_segment_fallback_roles WHERE segment_id = ?",
                    (str(segment_id),),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO catalog_segment_fallback_roles(segment_id, role)
                    VALUES (?, ?)
                    ON CONFLICT(segment_id) DO UPDATE SET role = excluded.role
                    """,
                    (str(segment_id), role),
                )

    def get_role(self, segment_id: UUID) -> SegmentFallbackRole:
        with self._catalog._connect() as connection:
            row = connection.execute(
                "SELECT role FROM catalog_segment_fallback_roles WHERE segment_id = ?",
                (str(segment_id),),
            ).fetchone()
        if row is None:
            return "normal"
        role = str(row["role"])
        return role if role in _ALLOWED else "normal"  # type: ignore[return-value]

    def list_ranges(
        self,
        role: SelectableFallbackRole,
        *,
        video_ids: list[UUID] | None = None,
        limit: int = 100,
    ) -> list[SegmentFallbackRange]:
        if role not in {"generic", "review_placeholder", "never"}:
            raise ValueError("list role must be generic, review_placeholder, or never")
        if limit <= 0:
            return []
        params: list[object] = [role]
        where = "r.role = ?"
        if video_ids is not None:
            if not video_ids:
                return []
            placeholders = ",".join("?" for _ in video_ids)
            where += f" AND s.video_id IN ({placeholders})"
            params.extend(str(video_id) for video_id in video_ids)
        params.append(limit)
        with self._catalog._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT r.segment_id, s.video_id, s.start_ms, s.end_ms
                FROM catalog_segment_fallback_roles AS r
                JOIN catalog_segments AS s ON s.id = r.segment_id
                WHERE {where}
                ORDER BY s.video_id, s.start_ms, s.end_ms
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [
            SegmentFallbackRange(
                segment_id=UUID(row["segment_id"]),
                video_id=UUID(row["video_id"]),
                start_ms=int(row["start_ms"]),
                end_ms=int(row["end_ms"]),
            )
            for row in rows
        ]

    def list_segments(
        self,
        role: SelectableFallbackRole,
        *,
        video_ids: list[UUID] | None = None,
        limit: int = 100,
    ) -> list[UUID]:
        return [
            item.segment_id
            for item in self.list_ranges(role, video_ids=video_ids, limit=limit)
        ]
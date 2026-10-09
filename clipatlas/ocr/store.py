import sqlite3
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from uuid import UUID

from clipatlas.library.fingerprint import canonicalize_path
from clipatlas.ocr.models import (
    OCRSampleRecord,
    OCRSampleStatus,
    OCRSpan,
    OCRTextMatch,
)

_HTML_MARKERS = (
    "<html",
    "<body",
    "<p",
    "<div",
    "<span",
    "<br",
    "<img",
    "<h1",
    "<h2",
    "<h3",
    "<h4",
    "<h5",
    "<h6",
)
_HTML_BLOCK_TAGS = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6"}


class _OCRHTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


class _OCRHTMLBlockExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[str] = []
        self._parts: list[str] = []

    def _flush(self) -> None:
        block = " ".join(" ".join(self._parts).split())
        self._parts.clear()
        if block:
            self.blocks.append(block)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in _HTML_BLOCK_TAGS or tag == "br":
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in _HTML_BLOCK_TAGS:
            self._flush()

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def finish(self) -> list[str]:
        self._flush()
        return self.blocks


def normalize_ocr_text(text: str) -> str:
    normalized_source = text
    folded = text.casefold()
    if any(marker in folded for marker in _HTML_MARKERS):
        parser = _OCRHTMLTextExtractor()
        parser.feed(text)
        parser.close()
        normalized_source = " ".join(parser.parts)
    return " ".join(normalized_source.split())


def normalize_ocr_search_text(text: str) -> str:
    return normalize_ocr_text(text).casefold()


def _searchable_ocr_blocks(text: str) -> list[str]:
    folded = text.casefold()
    if any(marker in folded for marker in _HTML_MARKERS):
        parser = _OCRHTMLBlockExtractor()
        parser.feed(text)
        parser.close()
        return parser.finish()
    return [
        normalized
        for line in text.splitlines()
        if (normalized := normalize_ocr_text(line))
    ]


def _matching_ocr_text(text: str, normalized_query: str) -> str:
    matches: list[str] = []
    seen: set[str] = set()
    for block in _searchable_ocr_blocks(text):
        folded = block.casefold()
        if normalized_query not in folded or folded in seen:
            continue
        seen.add(folded)
        matches.append(block)
    if matches:
        return " ".join(matches)

    normalized = normalize_ocr_text(text)
    if normalized_query in normalized.casefold():
        return normalized
    return ""


class OCRStore:
    """OCR persistence backed by the existing ClipAtlas library SQLite file."""

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
                CREATE TABLE IF NOT EXISTS catalog_ocr_samples (
                    video_id TEXT NOT NULL,
                    start_ms INTEGER NOT NULL,
                    end_ms INTEGER NOT NULL,
                    interval_ms INTEGER NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL,
                    last_error TEXT,
                    text TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (
                        video_id, start_ms, end_ms, interval_ms,
                        provider, model, revision
                    )
                );

                CREATE INDEX IF NOT EXISTS idx_catalog_ocr_samples_lookup
                ON catalog_ocr_samples(
                    video_id, provider, model, revision, interval_ms, start_ms
                );
                """
            )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> OCRSampleRecord:
        return OCRSampleRecord(
            video_id=UUID(row["video_id"]),
            start_ms=row["start_ms"],
            end_ms=row["end_ms"],
            interval_ms=row["interval_ms"],
            provider=row["provider"],
            model=row["model"],
            revision=row["revision"],
            status=OCRSampleStatus(row["status"]),
            attempt_count=row["attempt_count"],
            last_error=row["last_error"],
            text=row["text"],
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def save_sample(self, record: OCRSampleRecord) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO catalog_ocr_samples (
                    video_id, start_ms, end_ms, interval_ms, provider, model,
                    revision, status, attempt_count, last_error, text, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(
                    video_id, start_ms, end_ms, interval_ms,
                    provider, model, revision
                ) DO UPDATE SET
                    status = excluded.status,
                    attempt_count = excluded.attempt_count,
                    last_error = excluded.last_error,
                    text = excluded.text,
                    updated_at = excluded.updated_at
                """,
                (
                    str(record.video_id),
                    record.start_ms,
                    record.end_ms,
                    record.interval_ms,
                    record.provider,
                    record.model,
                    record.revision,
                    record.status.value,
                    record.attempt_count,
                    record.last_error,
                    record.text,
                    record.updated_at.isoformat(),
                ),
            )

    def get_sample(
        self,
        video_id: UUID,
        start_ms: int,
        end_ms: int,
        interval_ms: int,
        provider: str,
        model: str,
        *,
        revision: int,
    ) -> OCRSampleRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM catalog_ocr_samples
                WHERE video_id = ? AND start_ms = ? AND end_ms = ?
                    AND interval_ms = ? AND provider = ? AND model = ?
                    AND revision = ?
                LIMIT 1
                """,
                (
                    str(video_id),
                    start_ms,
                    end_ms,
                    interval_ms,
                    provider,
                    model,
                    revision,
                ),
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def get_latest_revision(
        self,
        video_id: UUID,
        provider: str,
        model: str,
        *,
        interval_ms: int,
    ) -> int | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT MAX(revision) AS revision
                FROM catalog_ocr_samples
                WHERE video_id = ? AND provider = ? AND model = ? AND interval_ms = ?
                """,
                (str(video_id), provider, model, interval_ms),
            ).fetchone()
        if row is None or row["revision"] is None:
            return None
        return int(row["revision"])

    def list_samples(
        self,
        video_id: UUID,
        provider: str | None = None,
        model: str | None = None,
        *,
        revision: int | None = None,
        interval_ms: int | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[OCRSampleRecord]:
        if (limit is not None and limit < 1) or offset < 0:
            raise ValueError("invalid pagination")
        query = """
            SELECT rowid, * FROM catalog_ocr_samples
            WHERE video_id = ?
        """
        parameters: list[object] = [str(video_id)]
        for column, value in (("provider", provider), ("model", model)):
            if value is not None:
                query += f" AND {column} = ?"
                parameters.append(value)
        if revision is not None:
            query += " AND revision = ?"
            parameters.append(revision)
        if interval_ms is not None:
            query += " AND interval_ms = ?"
            parameters.append(interval_ms)
        query += " ORDER BY revision, interval_ms, start_ms, end_ms, rowid"
        if limit is not None or offset:
            query += " LIMIT ? OFFSET ?"
            parameters.extend((limit if limit is not None else -1, offset))
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._from_row(row) for row in rows]

    def list_spans(
        self,
        video_id: UUID,
        provider: str,
        model: str,
        *,
        revision: int,
        interval_ms: int,
    ) -> list[OCRSpan]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT rowid, * FROM catalog_ocr_samples
                WHERE video_id = ? AND provider = ? AND model = ?
                    AND revision = ? AND interval_ms = ? AND status = ?
                ORDER BY start_ms, end_ms, rowid
                """,
                (
                    str(video_id),
                    provider,
                    model,
                    revision,
                    interval_ms,
                    OCRSampleStatus.COMPLETED.value,
                ),
            ).fetchall()

        spans: list[OCRSpan] = []
        current: OCRSpan | None = None
        for row in rows:
            record = self._from_row(row)
            normalized = normalize_ocr_text(record.text)
            if not normalized:
                if current is not None:
                    spans.append(current)
                    current = None
                continue
            if (
                current is not None
                and current.text == normalized
                and current.end_ms == record.start_ms
            ):
                current = current.model_copy(update={"end_ms": record.end_ms})
                continue
            if current is not None:
                spans.append(current)
            current = OCRSpan(
                start_ms=record.start_ms,
                end_ms=record.end_ms,
                text=normalized,
            )
        if current is not None:
            spans.append(current)
        return spans

    def search_text(
        self,
        query: str,
        provider: str,
        model: str,
        *,
        limit: int,
        video_ids: list[UUID] | None = None,
    ) -> list[OCRTextMatch]:
        normalized_query = normalize_ocr_search_text(query)
        if not normalized_query or limit <= 0:
            return []
        if video_ids is not None and not video_ids:
            return []

        conditions = ["provider = ?", "model = ?", "status = ?"]
        parameters: list[object] = [provider, model, OCRSampleStatus.COMPLETED.value]
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
                        PARTITION BY
                            video_id, start_ms, end_ms, interval_ms, provider, model
                        ORDER BY revision DESC, rowid DESC
                    ) AS rn
                FROM catalog_ocr_samples
                WHERE {where_clause}
            )
            SELECT * FROM ranked
            WHERE rn = 1 AND instr(lower(text), lower(?)) > 0
            ORDER BY video_id, start_ms, end_ms, interval_ms, source_rowid
        """
        parameters.append(normalized_query)

        with self._connect() as connection:
            rows = connection.execute(sql, parameters).fetchall()

        matches: list[OCRTextMatch] = []
        for row in rows:
            record = self._from_row(row)
            text = _matching_ocr_text(record.text, normalized_query)
            if not text:
                continue
            matches.append(
                OCRTextMatch(
                    video_id=record.video_id,
                    start_ms=record.start_ms,
                    end_ms=record.end_ms,
                    text=text,
                    revision=record.revision,
                    interval_ms=record.interval_ms,
                )
            )
            if len(matches) >= limit:
                break
        return matches

import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel

from clipatlas.domain.models import (
    AnnotationOrigin,
    SegmentSource,
    SemanticAnnotation,
    SemanticSpan,
    VideoAsset,
    VideoSegment,
)
from clipatlas.domain.visual_protocol import VideoSequenceWindow, VideoTimelineEvent
from clipatlas.catalog.timeline import build_sequence_windows, build_timeline_events
from clipatlas.library.fingerprint import canonicalize_path
from clipatlas.retrieval.models import QueryEmbedding, SegmentEmbedding, VideoChunkEmbedding
from clipatlas.video.models import IngestedVideo, MediaMetadata


class VideoAnnotationStats(BaseModel):
    segments_total: int
    annotated: int
    ai_effective: int
    human_effective: int
    locked: int


class VisualChunkSummary(BaseModel):
    start_ms: int
    end_ms: int
    provider: str
    model: str
    status: str
    dimensions: int | None
    chunk_duration_ms: int
    overlap_ms: int
    last_error: str | None
    thumbnail_url: str | None = None


class CatalogStore:
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
                CREATE TABLE IF NOT EXISTS catalog_videos (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    source_uri TEXT NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    fps REAL NOT NULL,
                    video_codec TEXT NOT NULL,
                    has_audio INTEGER NOT NULL,
                    project_id TEXT,
                    fallback_role TEXT NOT NULL DEFAULT 'normal',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS catalog_segments (
                    id TEXT PRIMARY KEY,
                    video_id TEXT NOT NULL,
                    start_ms INTEGER NOT NULL,
                    end_ms INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(video_id) REFERENCES catalog_videos(id)
                );

                CREATE INDEX IF NOT EXISTS idx_catalog_segments_video_start
                ON catalog_segments(video_id, start_ms, end_ms);

                CREATE TABLE IF NOT EXISTS catalog_segment_frames (
                    segment_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    uri TEXT NOT NULL,
                    PRIMARY KEY(segment_id, ordinal),
                    FOREIGN KEY(segment_id) REFERENCES catalog_segments(id)
                );

                CREATE TABLE IF NOT EXISTS catalog_annotations (
                    id TEXT PRIMARY KEY,
                    segment_id TEXT NOT NULL,
                    origin TEXT NOT NULL,
                    provider TEXT,
                    model TEXT,
                    description TEXT NOT NULL,
                    characters_json TEXT NOT NULL,
                    actions_json TEXT NOT NULL,
                    scene_json TEXT NOT NULL,
                    emotions_json TEXT NOT NULL,
                    objects_json TEXT NOT NULL,
                    ocr_json TEXT NOT NULL,
                    shot_type TEXT,
                    camera_motion TEXT,
                    facts_json TEXT NOT NULL DEFAULT '[]',
                    confidence REAL,
                    verified INTEGER NOT NULL,
                    locked INTEGER NOT NULL,
                    revision INTEGER NOT NULL,
                    raw_payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(segment_id) REFERENCES catalog_segments(id)
                );

                CREATE INDEX IF NOT EXISTS idx_catalog_annotations_segment_origin
                ON catalog_annotations(segment_id, origin, created_at);

                CREATE TABLE IF NOT EXISTS catalog_embeddings (
                    id TEXT PRIMARY KEY,
                    segment_id TEXT NOT NULL,
                    annotation_id TEXT NOT NULL,
                    annotation_revision INTEGER NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    dimensions INTEGER NOT NULL,
                    vector_json TEXT NOT NULL,
                    effective INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(segment_id) REFERENCES catalog_segments(id),
                    FOREIGN KEY(annotation_id) REFERENCES catalog_annotations(id)
                );

                CREATE INDEX IF NOT EXISTS idx_catalog_embeddings_lookup
                ON catalog_embeddings(provider, model, dimensions, effective);

                CREATE INDEX IF NOT EXISTS idx_catalog_embeddings_segment
                ON catalog_embeddings(segment_id, effective, created_at);

                CREATE UNIQUE INDEX IF NOT EXISTS idx_catalog_embeddings_one_effective
                ON catalog_embeddings(segment_id)
                WHERE effective = 1;

                CREATE TABLE IF NOT EXISTS catalog_video_chunk_embeddings (
                    id TEXT PRIMARY KEY,
                    video_id TEXT NOT NULL,
                    start_ms INTEGER NOT NULL,
                    end_ms INTEGER NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    dimensions INTEGER NOT NULL,
                    chunk_duration_ms INTEGER NOT NULL,
                    overlap_ms INTEGER NOT NULL,
                    vector_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(video_id) REFERENCES catalog_videos(id),
                    UNIQUE(
                        video_id, start_ms, end_ms, provider, model, dimensions,
                        chunk_duration_ms, overlap_ms
                    )
                );

                CREATE INDEX IF NOT EXISTS idx_catalog_video_chunk_embeddings_lookup
                ON catalog_video_chunk_embeddings(
                    video_id, provider, model, dimensions,
                    chunk_duration_ms, overlap_ms, start_ms
                );

                CREATE TABLE IF NOT EXISTS catalog_segment_media_types (
                    segment_id TEXT PRIMARY KEY,
                    subject_medium TEXT NOT NULL,
                    text_ratio REAL,
                    text_block_count INTEGER,
                    has_real_subject INTEGER,
                    basis TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(segment_id) REFERENCES catalog_segments(id)
                );

                CREATE TABLE IF NOT EXISTS catalog_contamination_ranges (
                    id TEXT PRIMARY KEY,
                    video_id TEXT NOT NULL,
                    segment_id TEXT,
                    start_ms INTEGER NOT NULL,
                    end_ms INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'annotation',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(video_id) REFERENCES catalog_videos(id),
                    FOREIGN KEY(segment_id) REFERENCES catalog_segments(id)
                );

                CREATE INDEX IF NOT EXISTS idx_catalog_contamination_segment
                ON catalog_contamination_ranges(segment_id, start_ms, end_ms);

                CREATE TABLE IF NOT EXISTS catalog_semantic_spans (
                    id TEXT PRIMARY KEY,
                    video_id TEXT NOT NULL,
                    start_ms INTEGER NOT NULL,
                    end_ms INTEGER NOT NULL,
                    safe_start_ms INTEGER NOT NULL,
                    safe_end_ms INTEGER NOT NULL,
                    summary TEXT NOT NULL,
                    subjects_json TEXT NOT NULL DEFAULT '[]',
                    actions_json TEXT NOT NULL DEFAULT '[]',
                    scenes_json TEXT NOT NULL DEFAULT '[]',
                    objects_json TEXT NOT NULL DEFAULT '[]',
                    facts_json TEXT NOT NULL DEFAULT '[]',
                    anchor_ranges_json TEXT NOT NULL DEFAULT '[]',
                    continuity_key TEXT NOT NULL,
                    visual_family TEXT,
                    presentation_type TEXT,
                    pollution_level TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(video_id) REFERENCES catalog_videos(id)
                );

                CREATE TABLE IF NOT EXISTS catalog_semantic_span_segments (
                    span_id TEXT NOT NULL,
                    segment_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    PRIMARY KEY(span_id, segment_id),
                    FOREIGN KEY(span_id) REFERENCES catalog_semantic_spans(id),
                    FOREIGN KEY(segment_id) REFERENCES catalog_segments(id)
                );

                CREATE INDEX IF NOT EXISTS idx_catalog_semantic_span_video
                ON catalog_semantic_spans(video_id, start_ms, end_ms);

                CREATE INDEX IF NOT EXISTS idx_catalog_semantic_span_segment
                ON catalog_semantic_span_segments(segment_id, span_id);

                CREATE TABLE IF NOT EXISTS catalog_timeline_events (
                    id TEXT PRIMARY KEY,
                    video_id TEXT NOT NULL,
                    start_ms INTEGER NOT NULL,
                    end_ms INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    protocol_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(video_id) REFERENCES catalog_videos(id)
                );

                CREATE INDEX IF NOT EXISTS idx_catalog_timeline_events_video_time
                ON catalog_timeline_events(video_id, start_ms, end_ms);

                CREATE TABLE IF NOT EXISTS catalog_sequence_windows (
                    id TEXT PRIMARY KEY,
                    video_id TEXT NOT NULL,
                    start_ms INTEGER NOT NULL,
                    end_ms INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    protocol_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(video_id) REFERENCES catalog_videos(id)
                );

                CREATE INDEX IF NOT EXISTS idx_catalog_sequence_windows_video_time
                ON catalog_sequence_windows(video_id, start_ms, end_ms);

                CREATE TABLE IF NOT EXISTS retrieval_query_embeddings (
                    requirement_id TEXT NOT NULL,
                    source_text_hash TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    dimensions INTEGER NOT NULL,
                    protocol_version TEXT NOT NULL,
                    event_index_revision TEXT NOT NULL,
                    vector_json TEXT NOT NULL,
                    api_request_count INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (
                        requirement_id, source_text_hash, provider, model, dimensions,
                        protocol_version, event_index_revision
                    )
                );
                """
            )
            try:
                connection.execute(
                    "ALTER TABLE catalog_segment_media_types "
                    "ADD COLUMN text_block_count INTEGER"
                )
            except sqlite3.OperationalError:
                # column already exists (fresh or previously migrated database)
                pass
            try:
                connection.execute(
                    "ALTER TABLE retrieval_query_embeddings "
                    "ADD COLUMN api_request_count INTEGER NOT NULL DEFAULT 1"
                )
            except sqlite3.OperationalError:
                pass
            try:
                connection.execute(
                    "ALTER TABLE catalog_annotations "
                    "ADD COLUMN facts_json TEXT NOT NULL DEFAULT '[]'"
                )
            except sqlite3.OperationalError:
                pass
            try:
                connection.execute(
                    "ALTER TABLE catalog_videos ADD COLUMN project_id TEXT"
                )
            except sqlite3.OperationalError:
                pass  # 列已存在
            try:
                connection.execute(
                    "ALTER TABLE catalog_videos ADD COLUMN fallback_role TEXT NOT NULL DEFAULT 'normal'"
                )
            except sqlite3.OperationalError:
                pass  # 列已存在

            for column, definition in (
                ("subjects_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("actions_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("scenes_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("objects_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("facts_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("anchor_ranges_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("visual_family", "TEXT"),
                ("presentation_type", "TEXT"),
            ):
                try:
                    connection.execute(
                        f"ALTER TABLE catalog_semantic_spans ADD COLUMN {column} {definition}"
                    )
                except sqlite3.OperationalError:
                    pass

    def save_prepared_video(
        self,
        prepared: IngestedVideo,
        project_id: UUID | None = None,
    ) -> None:
        video = prepared.video
        metadata = prepared.metadata
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO catalog_videos (
                    id, filename, source_uri, duration_ms, width, height, fps,
                    video_codec, has_audio, project_id, fallback_role, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    filename = excluded.filename,
                    source_uri = excluded.source_uri,
                    duration_ms = excluded.duration_ms,
                    width = excluded.width,
                    height = excluded.height,
                    fps = excluded.fps,
                    video_codec = excluded.video_codec,
                    has_audio = excluded.has_audio,
                    project_id = COALESCE(catalog_videos.project_id, excluded.project_id),
                    fallback_role = catalog_videos.fallback_role,
                    created_at = excluded.created_at
                """,
                (
                    str(video.id),
                    video.filename,
                    video.source_uri,
                    metadata.duration_ms,
                    metadata.width,
                    metadata.height,
                    metadata.fps,
                    metadata.video_codec,
                    int(metadata.has_audio),
                    str(project_id) if project_id else None,
                    video.fallback_role,
                    video.created_at.isoformat(),
                ),
            )
            for segment in prepared.segments:
                connection.execute(
                    """
                    INSERT INTO catalog_segments (
                        id, video_id, start_ms, end_ms, source, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        video_id = excluded.video_id,
                        start_ms = excluded.start_ms,
                        end_ms = excluded.end_ms,
                        source = excluded.source,
                        created_at = excluded.created_at
                    """,
                    (
                        str(segment.id),
                        str(segment.video_id),
                        segment.start_ms,
                        segment.end_ms,
                        segment.source.value,
                        segment.created_at.isoformat(),
                    ),
                )
                connection.execute(
                    "DELETE FROM catalog_segment_frames WHERE segment_id = ?",
                    (str(segment.id),),
                )
                for ordinal, uri in enumerate(prepared.frames_by_segment.get(segment.id, [])):
                    connection.execute(
                        """
                        INSERT INTO catalog_segment_frames (segment_id, ordinal, uri)
                        VALUES (?, ?, ?)
                        """,
                        (str(segment.id), ordinal, uri),
                    )

    def get_ingested_video(self, video_id: UUID) -> IngestedVideo | None:
        with self._connect() as connection:
            video_row = connection.execute(
                "SELECT * FROM catalog_videos WHERE id = ?",
                (str(video_id),),
            ).fetchone()
            if video_row is None:
                return None
            segment_rows = connection.execute(
                """
                SELECT * FROM catalog_segments
                WHERE video_id = ?
                ORDER BY start_ms, end_ms, id
                """,
                (str(video_id),),
            ).fetchall()
            frame_rows = connection.execute(
                """
                SELECT f.segment_id, f.uri
                FROM catalog_segment_frames AS f
                JOIN catalog_segments AS s ON s.id = f.segment_id
                WHERE s.video_id = ?
                ORDER BY s.start_ms, f.ordinal
                """,
                (str(video_id),),
            ).fetchall()

        video = VideoAsset(
            id=UUID(video_row["id"]),
            filename=video_row["filename"],
            source_uri=video_row["source_uri"],
            duration_ms=video_row["duration_ms"],
            width=video_row["width"],
            height=video_row["height"],
            fps=video_row["fps"],
            created_at=datetime.fromisoformat(video_row["created_at"]),
            fallback_role=(
                video_row["fallback_role"]
                if "fallback_role" in video_row.keys() else "normal"
            ),
        )
        metadata = MediaMetadata(
            duration_ms=video_row["duration_ms"],
            width=video_row["width"],
            height=video_row["height"],
            fps=video_row["fps"],
            video_codec=video_row["video_codec"],
            has_audio=bool(video_row["has_audio"]),
        )
        segments = [
            VideoSegment(
                id=UUID(row["id"]),
                video_id=UUID(row["video_id"]),
                start_ms=row["start_ms"],
                end_ms=row["end_ms"],
                source=SegmentSource(row["source"]),
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in segment_rows
        ]
        frames_by_segment: dict[UUID, list[str]] = {segment.id: [] for segment in segments}
        for row in frame_rows:
            frames_by_segment.setdefault(UUID(row["segment_id"]), []).append(row["uri"])
        return IngestedVideo(
            video=video,
            metadata=metadata,
            segments=segments,
            frames_by_segment=frames_by_segment,
        )

    def save_annotation(self, annotation: SemanticAnnotation) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO catalog_annotations (
                    id, segment_id, origin, provider, model, description,
                    characters_json, actions_json, scene_json, emotions_json,
                    objects_json, ocr_json, shot_type, camera_motion, facts_json, confidence,
                    verified, locked, revision, raw_payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO NOTHING
                """,
                (
                    str(annotation.id),
                    str(annotation.segment_id),
                    annotation.origin.value,
                    annotation.provider,
                    annotation.model,
                    annotation.description,
                    json.dumps(annotation.characters, ensure_ascii=False),
                    json.dumps(annotation.actions, ensure_ascii=False),
                    json.dumps(annotation.scene, ensure_ascii=False),
                    json.dumps(annotation.emotions, ensure_ascii=False),
                    json.dumps(annotation.objects, ensure_ascii=False),
                    json.dumps(annotation.ocr, ensure_ascii=False),
                    annotation.shot_type,
                    annotation.camera_motion,
                    json.dumps(
                        [fact.model_dump(mode="json") for fact in annotation.facts],
                        ensure_ascii=False,
                    ),
                    annotation.confidence,
                    int(annotation.verified),
                    int(annotation.locked),
                    annotation.revision,
                    json.dumps(annotation.raw_payload, ensure_ascii=False),
                    annotation.created_at.isoformat(),
                ),
            )

    @staticmethod
    def _annotation_from_row(row: sqlite3.Row) -> SemanticAnnotation:
        return SemanticAnnotation(
            id=UUID(row["id"]),
            segment_id=UUID(row["segment_id"]),
            origin=AnnotationOrigin(row["origin"]),
            provider=row["provider"],
            model=row["model"],
            description=row["description"],
            characters=json.loads(row["characters_json"]),
            actions=json.loads(row["actions_json"]),
            scene=json.loads(row["scene_json"]),
            emotions=json.loads(row["emotions_json"]),
            objects=json.loads(row["objects_json"]),
            ocr=json.loads(row["ocr_json"]),
            shot_type=row["shot_type"],
            camera_motion=row["camera_motion"],
            facts=json.loads(row["facts_json"]) if "facts_json" in row.keys() else [],
            confidence=row["confidence"],
            verified=bool(row["verified"]),
            locked=bool(row["locked"]),
            revision=row["revision"],
            raw_payload=json.loads(row["raw_payload_json"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def list_annotations(
        self,
        segment_id: UUID,
        origin: AnnotationOrigin | None = None,
    ) -> list[SemanticAnnotation]:
        query = "SELECT rowid, * FROM catalog_annotations WHERE segment_id = ?"
        parameters: list[object] = [str(segment_id)]
        if origin is not None:
            query += " AND origin = ?"
            parameters.append(origin.value)
        query += " ORDER BY created_at, rowid"
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._annotation_from_row(row) for row in rows]

    def get_effective_annotation(self, segment_id: UUID) -> SemanticAnnotation | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT rowid, *
                FROM catalog_annotations
                WHERE segment_id = ?
                ORDER BY
                    CASE WHEN origin = ? THEN 0 ELSE 1 END,
                    revision DESC,
                    created_at DESC,
                    rowid DESC
                LIMIT 1
                """,
                (str(segment_id), AnnotationOrigin.HUMAN.value),
            ).fetchone()
        return self._annotation_from_row(row) if row is not None else None

    @staticmethod
    def _timeline_event_from_row(row: sqlite3.Row) -> VideoTimelineEvent:
        return VideoTimelineEvent.model_validate_json(row["payload_json"])

    @staticmethod
    def _sequence_window_from_row(row: sqlite3.Row) -> VideoSequenceWindow:
        return VideoSequenceWindow.model_validate_json(row["payload_json"])

    def list_timeline_events(
        self,
        video_id: UUID,
        *,
        limit: int = 10_000,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> list[VideoTimelineEvent]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload_json FROM catalog_timeline_events
                WHERE video_id = ?
                  AND (? IS NULL OR end_ms > ?)
                  AND (? IS NULL OR start_ms < ?)
                ORDER BY start_ms, end_ms, id LIMIT ?
                """,
                (str(video_id), start_ms, start_ms, end_ms, end_ms, limit),
            ).fetchall()
        return [self._timeline_event_from_row(row) for row in rows]

    def list_sequence_windows(
        self,
        video_id: UUID,
        *,
        limit: int = 10_000,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> list[VideoSequenceWindow]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload_json FROM catalog_sequence_windows
                WHERE video_id = ?
                  AND (? IS NULL OR end_ms > ?)
                  AND (? IS NULL OR start_ms < ?)
                ORDER BY start_ms, end_ms, id LIMIT ?
                """,
                (str(video_id), start_ms, start_ms, end_ms, end_ms, limit),
            ).fetchall()
        return [self._sequence_window_from_row(row) for row in rows]

    def rebuild_timeline_protocol(self, video_id: UUID) -> tuple[int, int]:
        """Rebuild local event/window records without any provider call."""
        segments = self.list_segments(video_id, limit=1_000_000, offset=0)
        events: list[VideoTimelineEvent] = []
        for segment in segments:
            events.extend(build_timeline_events(segment, self.get_effective_annotation(segment.id)))
        source_cuts = [
            left.end_ms
            for left, right in zip(segments, segments[1:])
            if left.source.value == "scene_detection" and left.end_ms == right.start_ms
        ]
        with self._connect() as connection:
            contamination_rows = connection.execute(
                "SELECT start_ms,end_ms,kind FROM catalog_contamination_ranges WHERE video_id=?",
                (str(video_id),),
            ).fetchall()
        severe_tokens = ("black", "transition", "blur", "occlusion", "copyright")
        pollution_ranges = [
            (int(row["start_ms"]), int(row["end_ms"]), str(row["kind"]))
            for row in contamination_rows
            if any(token in str(row["kind"]).casefold() for token in severe_tokens)
        ]
        windows = build_sequence_windows(
            events,
            source_cut_boundaries=source_cuts,
            pollution_ranges=pollution_ranges,
        )
        with self._connect() as connection:
            connection.execute("DELETE FROM catalog_timeline_events WHERE video_id=?", (str(video_id),))
            connection.execute("DELETE FROM catalog_sequence_windows WHERE video_id=?", (str(video_id),))
            connection.executemany(
                """
                INSERT INTO catalog_timeline_events
                    (id, video_id, start_ms, end_ms, payload_json, protocol_version, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (str(event.id), str(event.video_id), event.start_ms, event.end_ms,
                     event.model_dump_json(), event.protocol_version, event.created_at.isoformat())
                    for event in events
                ],
            )
            connection.executemany(
                """
                INSERT INTO catalog_sequence_windows
                    (id, video_id, start_ms, end_ms, payload_json, protocol_version, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (str(window.id), str(window.video_id), window.start_ms, window.end_ms,
                     window.model_dump_json(), window.protocol_version, window.created_at.isoformat())
                    for window in windows
                ],
            )
        return len(events), len(windows)

    def has_ai_annotation(self, segment_id: UUID, provider: str | None = None) -> bool:
        query = "SELECT 1 FROM catalog_annotations WHERE segment_id = ? AND origin = ?"
        parameters: list[object] = [str(segment_id), AnnotationOrigin.AI.value]
        if provider is not None:
            query += " AND provider = ?"
            parameters.append(provider)
        query += " LIMIT 1"
        with self._connect() as connection:
            row = connection.execute(query, parameters).fetchone()
        return row is not None

    def search_annotations_by_keywords(
        self,
        keywords: list[str],
        *,
        limit: int = 12,
        video_ids: list[UUID] | None = None,
    ) -> list[tuple[UUID, SemanticAnnotation]]:
        """Local keyword recall over annotation facts (zero API).

        Matches keywords against description / objects / actions / scene / fourteen-layer facts
        columns of the permanent annotation table and returns
        ``(segment_id, effective annotation)`` pairs ranked by hit count.
        Used by the rough-cut planner as the primary local retrieval source.
        """
        if not keywords:
            return []
        clauses: list[str] = []
        score_clauses: list[str] = []
        score_params: list[object] = []
        where_params: list[object] = []
        for keyword in keywords[:32]:
            like = f"%{keyword}%"
            condition = (
                "(description LIKE ? OR objects_json LIKE ? "
                "OR actions_json LIKE ? OR scene_json LIKE ? "
                "OR facts_json LIKE ? OR characters_json LIKE ? "
                "OR emotions_json LIKE ? OR ocr_json LIKE ?)"
            )
            clauses.append(condition)
            score_clauses.append(f"CASE WHEN {condition} THEN 1 ELSE 0 END")
            score_params.extend([like] * 8)
            where_params.extend([like] * 8)
        where = f"({' OR '.join(clauses)})"
        video_params: list[object] = []
        if video_ids is not None:
            if not video_ids:
                return []
            placeholders = ",".join("?" for _ in video_ids)
            where += (
                " AND segment_id IN ("
                "SELECT id FROM catalog_segments WHERE video_id IN "
                f"({placeholders}))"
            )
            video_params.extend(str(video_id) for video_id in video_ids)
        params = [*score_params, *where_params, *video_params, limit]
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                WITH ranked AS (
                    SELECT *, ROW_NUMBER() OVER (
                        PARTITION BY segment_id
                        ORDER BY CASE WHEN origin = ? THEN 0 ELSE 1 END,
                                 revision DESC, created_at DESC, rowid DESC
                    ) AS effective_rank
                    FROM catalog_annotations
                )
                SELECT *, ({' + '.join(score_clauses)}) AS hit_count
                FROM ranked
                WHERE effective_rank = 1 AND {where}
                ORDER BY hit_count DESC, created_at DESC, segment_id
                LIMIT ?
                """,
                [AnnotationOrigin.HUMAN.value, *params],
            ).fetchall()
        return [(UUID(row["segment_id"]), self._annotation_from_row(row)) for row in rows]

    def search_segments_by_filename(
        self,
        keywords: list[str],
        *,
        limit: int = 12,
        video_ids: list[UUID] | None = None,
    ) -> list[tuple[UUID, UUID, int, int, str, str]]:
        """按素材文件名关键词召回 segment（本地、零 API）。

        视频文件名通常是素材的主题标签（如“华为乾崑200万里程碑视频”），
        中文关键词直接 LIKE 命中即可召回，不依赖英文标注。
        返回 (segment_id, video_id, start_ms, end_ms, filename, source_uri)。
        """
        if not keywords:
            return []
        clauses: list[str] = []
        params: list[object] = []
        for keyword in keywords[:16]:
            clauses.append("v.filename LIKE ?")
            params.append(f"%{keyword}%")
        where = "(" + " OR ".join(clauses) + ")"
        if video_ids is not None:
            if not video_ids:
                return []
            placeholders = ",".join("?" for _ in video_ids)
            where += f" AND v.id IN ({placeholders})"
            params.extend(str(video_id) for video_id in video_ids)
        params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT s.id, s.video_id, s.start_ms, s.end_ms, v.filename, v.source_uri
                FROM catalog_segments s
                JOIN catalog_videos v ON v.id = s.video_id
                WHERE {where}
                ORDER BY (s.end_ms - s.start_ms) DESC, s.start_ms
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [
            (
                UUID(row["id"]), UUID(row["video_id"]), row["start_ms"],
                row["end_ms"], row["filename"], row["source_uri"],
            )
            for row in rows
        ]

    @staticmethod
    def _embedding_from_row(row: sqlite3.Row) -> SegmentEmbedding:
        return SegmentEmbedding(
            id=UUID(row["id"]),
            segment_id=UUID(row["segment_id"]),
            annotation_id=UUID(row["annotation_id"]),
            annotation_revision=row["annotation_revision"],
            provider=row["provider"],
            model=row["model"],
            dimensions=row["dimensions"],
            vector=json.loads(row["vector_json"]),
            effective=bool(row["effective"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def save_embedding(self, record: SegmentEmbedding) -> None:
        with self._connect() as connection:
            if record.effective:
                connection.execute(
                    """
                    UPDATE catalog_embeddings
                    SET effective = 0
                    WHERE segment_id = ? AND id != ? AND effective = 1
                    """,
                    (str(record.segment_id), str(record.id)),
                )
            connection.execute(
                """
                INSERT INTO catalog_embeddings (
                    id, segment_id, annotation_id, annotation_revision,
                    provider, model, dimensions, vector_json, effective, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    segment_id = excluded.segment_id,
                    annotation_id = excluded.annotation_id,
                    annotation_revision = excluded.annotation_revision,
                    provider = excluded.provider,
                    model = excluded.model,
                    dimensions = excluded.dimensions,
                    vector_json = excluded.vector_json,
                    effective = excluded.effective,
                    created_at = excluded.created_at
                """,
                (
                    str(record.id),
                    str(record.segment_id),
                    str(record.annotation_id),
                    record.annotation_revision,
                    record.provider,
                    record.model,
                    record.dimensions,
                    json.dumps(record.vector),
                    int(record.effective),
                    record.created_at.isoformat(),
                ),
            )

    def get_effective_embedding(
        self,
        segment_id: UUID,
        provider: str,
        model: str,
        dimensions: int,
    ) -> SegmentEmbedding | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM catalog_embeddings
                WHERE segment_id = ? AND provider = ? AND model = ?
                    AND dimensions = ? AND effective = 1
                LIMIT 1
                """,
                (str(segment_id), provider, model, dimensions),
            ).fetchone()
        return self._embedding_from_row(row) if row is not None else None

    def list_effective_embeddings(
        self,
        provider: str,
        model: str,
        dimensions: int,
    ) -> list[SegmentEmbedding]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT rowid, * FROM catalog_embeddings
                WHERE provider = ? AND model = ? AND dimensions = ? AND effective = 1
                ORDER BY created_at, rowid
                """,
                (provider, model, dimensions),
            ).fetchall()
        return [self._embedding_from_row(row) for row in rows]

    def deactivate_segment_embeddings(self, segment_id: UUID) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE catalog_embeddings SET effective = 0 WHERE segment_id = ?",
                (str(segment_id),),
            )

    @staticmethod
    def _video_chunk_embedding_from_row(row: sqlite3.Row) -> VideoChunkEmbedding:
        return VideoChunkEmbedding(
            id=UUID(row["id"]),
            video_id=UUID(row["video_id"]),
            start_ms=row["start_ms"],
            end_ms=row["end_ms"],
            provider=row["provider"],
            model=row["model"],
            dimensions=row["dimensions"],
            chunk_duration_ms=row["chunk_duration_ms"],
            overlap_ms=row["overlap_ms"],
            vector=json.loads(row["vector_json"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def save_video_chunk_embedding(self, record: VideoChunkEmbedding) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO catalog_video_chunk_embeddings (
                    id, video_id, start_ms, end_ms, provider, model, dimensions,
                    chunk_duration_ms, overlap_ms, vector_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(
                    video_id, start_ms, end_ms, provider, model, dimensions,
                    chunk_duration_ms, overlap_ms
                ) DO UPDATE SET
                    id = excluded.id,
                    vector_json = excluded.vector_json,
                    created_at = excluded.created_at
                """,
                (
                    str(record.id),
                    str(record.video_id),
                    record.start_ms,
                    record.end_ms,
                    record.provider,
                    record.model,
                    record.dimensions,
                    record.chunk_duration_ms,
                    record.overlap_ms,
                    json.dumps(record.vector),
                    record.created_at.isoformat(),
                ),
            )

    def get_video_chunk_embedding(
        self,
        video_id: UUID,
        *,
        start_ms: int,
        end_ms: int,
        provider: str,
        model: str,
        dimensions: int,
        chunk_duration_ms: int,
        overlap_ms: int,
    ) -> VideoChunkEmbedding | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM catalog_video_chunk_embeddings
                WHERE video_id = ? AND start_ms = ? AND end_ms = ?
                    AND provider = ? AND model = ? AND dimensions = ?
                    AND chunk_duration_ms = ? AND overlap_ms = ?
                LIMIT 1
                """,
                (
                    str(video_id),
                    start_ms,
                    end_ms,
                    provider,
                    model,
                    dimensions,
                    chunk_duration_ms,
                    overlap_ms,
                ),
            ).fetchone()
        return self._video_chunk_embedding_from_row(row) if row is not None else None

    def list_video_chunk_embeddings(
        self,
        video_id: UUID,
        *,
        provider: str,
        model: str,
        dimensions: int,
        chunk_duration_ms: int,
        overlap_ms: int,
    ) -> list[VideoChunkEmbedding]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT rowid, * FROM catalog_video_chunk_embeddings
                WHERE video_id = ? AND provider = ? AND model = ? AND dimensions = ?
                    AND chunk_duration_ms = ? AND overlap_ms = ?
                ORDER BY start_ms, end_ms, rowid
                """,
                (
                    str(video_id),
                    provider,
                    model,
                    dimensions,
                    chunk_duration_ms,
                    overlap_ms,
                ),
            ).fetchall()
        return [self._video_chunk_embedding_from_row(row) for row in rows]

    def list_video_chunk_embeddings_for_search(
        self,
        *,
        provider: str,
        model: str,
        dimensions: int,
        chunk_duration_ms: int,
        overlap_ms: int,
        video_ids: list[UUID] | None = None,
    ) -> list[VideoChunkEmbedding]:
        query = """
            SELECT rowid, * FROM catalog_video_chunk_embeddings
            WHERE provider = ? AND model = ? AND dimensions = ?
                AND chunk_duration_ms = ? AND overlap_ms = ?
        """
        parameters: list[object] = [
            provider,
            model,
            dimensions,
            chunk_duration_ms,
            overlap_ms,
        ]
        if video_ids is not None:
            if not video_ids:
                return []
            placeholders = ", ".join("?" for _ in video_ids)
            query += f" AND video_id IN ({placeholders})"
            parameters.extend(str(video_id) for video_id in video_ids)
        query += " ORDER BY video_id, start_ms, end_ms, rowid"
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._video_chunk_embedding_from_row(row) for row in rows]

    def list_visual_chunk_summaries(
        self, video_id: UUID, *, limit: int, offset: int = 0,
    ) -> list[VisualChunkSummary]:
        """Paginated display projection; never reads or deserializes vector_json."""
        if limit < 1 or offset < 0:
            raise ValueError("invalid pagination")
        with self._connect() as connection:
            rows = connection.execute(
                """
                WITH summaries AS (
                    SELECT c.start_ms, c.end_ms, c.provider, c.model, c.status,
                           e.dimensions, c.chunk_duration_ms, c.overlap_ms, c.last_error
                    FROM catalog_video_chunk_checkpoints c
                    LEFT JOIN catalog_video_chunk_embeddings e
                      USING (video_id, start_ms, end_ms, provider, model,
                             chunk_duration_ms, overlap_ms)
                    WHERE c.video_id = ?
                    UNION ALL
                    SELECT e.start_ms, e.end_ms, e.provider, e.model, 'untracked',
                           e.dimensions, e.chunk_duration_ms, e.overlap_ms, NULL
                    FROM catalog_video_chunk_embeddings e
                    WHERE e.video_id = ? AND NOT EXISTS (
                        SELECT 1 FROM catalog_video_chunk_checkpoints c
                        WHERE c.video_id = e.video_id AND c.start_ms = e.start_ms
                          AND c.end_ms = e.end_ms AND c.provider = e.provider
                          AND c.model = e.model AND c.chunk_duration_ms = e.chunk_duration_ms
                          AND c.overlap_ms = e.overlap_ms
                    )
                )
                SELECT * FROM summaries
                ORDER BY start_ms, end_ms, provider, model, chunk_duration_ms,
                         overlap_ms, dimensions
                LIMIT ? OFFSET ?
                """,
                (str(video_id), str(video_id), limit, offset),
            ).fetchall()
        return [VisualChunkSummary(**dict(row)) for row in rows]

    def get_video_frame_uri(self, video_id: UUID, timestamp_ms: int) -> str | None:
        """One existing representative frame from the scene containing this time."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT f.uri FROM catalog_segments s
                JOIN catalog_segment_frames f ON f.segment_id = s.id
                WHERE s.video_id = ? AND s.start_ms <= ? AND s.end_ms > ?
                ORDER BY s.start_ms DESC, s.id, f.ordinal
                LIMIT 1
                """,
                (str(video_id), timestamp_ms, timestamp_ms),
            ).fetchone()
        return str(row["uri"]) if row is not None else None

    def list_segment_ids(self, limit: int | None = None) -> list[UUID]:
        if limit is not None and limit <= 0:
            return []
        query = "SELECT id FROM catalog_segments ORDER BY rowid"
        parameters: tuple[int, ...] = ()
        if limit is not None:
            query += " LIMIT ?"
            parameters = (limit,)
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [UUID(row["id"]) for row in rows]

    def get_segment(self, segment_id: UUID) -> VideoSegment | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM catalog_segments WHERE id = ?",
                (str(segment_id),),
            ).fetchone()
        if row is None:
            return None
        return VideoSegment(
            id=UUID(row["id"]),
            video_id=UUID(row["video_id"]),
            start_ms=row["start_ms"],
            end_ms=row["end_ms"],
            source=SegmentSource(row["source"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def get_video(self, video_id: UUID) -> VideoAsset | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM catalog_videos WHERE id = ?",
                (str(video_id),),
            ).fetchone()
        if row is None:
            return None
        return VideoAsset(
            id=UUID(row["id"]),
            filename=row["filename"],
            source_uri=row["source_uri"],
            duration_ms=row["duration_ms"],
            width=row["width"],
            height=row["height"],
            fps=row["fps"],
            created_at=datetime.fromisoformat(row["created_at"]),
            fallback_role=row["fallback_role"] if "fallback_role" in row.keys() else "normal",
        )

    def list_video_ids(self, *, limit: int = 100, offset: int = 0) -> list[UUID]:
        if limit < 1 or offset < 0:
            raise ValueError("invalid pagination")
        with self._connect() as connection:
            rows = connection.execute("SELECT id FROM catalog_videos ORDER BY id LIMIT ? OFFSET ?",
                                      (limit, offset)).fetchall()
        return [UUID(row["id"]) for row in rows]

    def list_video_ids_for_project(
        self, project_id: UUID, *, limit: int = 1_000_000,
    ) -> list[UUID]:
        """Return only videos owned by this project."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id FROM catalog_videos "
                "WHERE project_id = ? ORDER BY id LIMIT ?",
                (str(project_id), limit),
            ).fetchall()
        return [UUID(row["id"]) for row in rows]

    def set_video_fallback_role(self, video_id: UUID, role: str) -> None:
        if role not in {"normal", "generic", "never"}:
            raise ValueError("fallback role must be normal, generic, or never")
        with self._connect() as connection:
            updated = connection.execute(
                "UPDATE catalog_videos SET fallback_role = ? WHERE id = ?",
                (role, str(video_id)),
            ).rowcount
        if not updated:
            raise KeyError(video_id)

    def get_segment_media_type(
        self,
        segment_id: UUID,
    ) -> tuple[str, str, float | None, int | None] | None:
        """Return (subject_medium, basis, text_ratio, text_block_count) or None."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT subject_medium, basis, text_ratio, text_block_count "
                "FROM catalog_segment_media_types WHERE segment_id = ?",
                (str(segment_id),),
            ).fetchone()
        if row is None:
            return None
        return (
            row["subject_medium"],
            row["basis"],
            row["text_ratio"],
            row["text_block_count"],
        )

    def save_segment_media_type(
        self,
        *,
        segment_id: UUID,
        subject_medium: str,
        text_ratio: float | None,
        text_block_count: int | None,
        has_real_subject: bool | None,
        basis: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO catalog_segment_media_types (
                    segment_id, subject_medium, text_ratio, text_block_count,
                    has_real_subject, basis, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(segment_id) DO UPDATE SET
                    subject_medium = excluded.subject_medium,
                    text_ratio = excluded.text_ratio,
                    text_block_count = excluded.text_block_count,
                    has_real_subject = excluded.has_real_subject,
                    basis = excluded.basis,
                    created_at = excluded.created_at
                """,
                (
                    str(segment_id),
                    subject_medium,
                    text_ratio,
                    text_block_count,
                    int(bool(has_real_subject)) if has_real_subject is not None else None,
                    basis,
                    datetime.now(UTC).isoformat(),
                ),
            )

    def save_query_embedding(self, record: QueryEmbedding) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO retrieval_query_embeddings (
                    requirement_id, source_text_hash, provider, model, dimensions,
                    protocol_version, event_index_revision, vector_json,
                    api_request_count, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.requirement_id,
                    record.source_text_hash,
                    record.provider,
                    record.model,
                    record.dimensions,
                    record.protocol_version,
                    record.event_index_revision,
                    json.dumps(record.vector),
                    record.api_request_count,
                    record.created_at.isoformat(),
                ),
            )

    def get_query_embedding(
        self,
        requirement_id: str,
        *,
        source_text_hash: str,
        provider: str,
        model: str,
        dimensions: int,
        protocol_version: str,
        event_index_revision: str,
    ) -> QueryEmbedding | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM retrieval_query_embeddings
                WHERE requirement_id=? AND source_text_hash=? AND provider=? AND model=?
                  AND dimensions=? AND protocol_version=? AND event_index_revision=?
                """,
                (
                    requirement_id, source_text_hash, provider, model, dimensions,
                    protocol_version, event_index_revision,
                ),
            ).fetchone()
        if row is None:
            return None
        return QueryEmbedding(
            requirement_id=row["requirement_id"],
            source_text_hash=row["source_text_hash"],
            provider=row["provider"],
            model=row["model"],
            dimensions=row["dimensions"],
            protocol_version=row["protocol_version"],
            event_index_revision=row["event_index_revision"],
            vector=json.loads(row["vector_json"]),
            api_request_count=row["api_request_count"] if "api_request_count" in row.keys() else 1,
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def get_segment_contamination_kinds(self, segment_id: UUID) -> list[str]:
        with self._connect() as connection:
            segment = connection.execute(
                "SELECT video_id,start_ms,end_ms FROM catalog_segments WHERE id=?",
                (str(segment_id),),
            ).fetchone()
            if segment is None:
                return []
            rows = connection.execute(
                "SELECT DISTINCT kind FROM catalog_contamination_ranges "
                "WHERE (segment_id = ?) OR (video_id = ? AND start_ms < ? AND end_ms > ?) "
                "ORDER BY kind",
                (str(segment_id), segment["video_id"], segment["end_ms"], segment["start_ms"]),
            ).fetchall()
        return [str(row["kind"]) for row in rows]

    @staticmethod
    def _span_features(text: str) -> set[str]:
        folded = text.casefold()
        features = set(re.findall(r"[a-z][a-z0-9-]{2,}", folded))
        cjk = "".join(re.findall(r"[\u4e00-\u9fff]", folded))
        features.update(cjk[index:index + 2] for index in range(len(cjk) - 1))
        return features

    def rebuild_semantic_spans(
        self, video_id: UUID, *, maximum_span_ms: int = 30_000,
    ) -> int:
        """Derive continuous edit windows locally from persisted annotations.

        Short evidence segments are merged only across adjacent, editable
        ranges with compatible semantic features. Hard pollution is a boundary,
        while text-heavy real footage remains usable at lower priority.
        """
        with self._connect() as connection:
            rows = connection.execute(
                """
                WITH effective AS (
                    SELECT *, ROW_NUMBER() OVER (
                        PARTITION BY segment_id
                        ORDER BY CASE WHEN origin = 'human' THEN 0 ELSE 1 END,
                                 revision DESC, created_at DESC, rowid DESC
                    ) AS rn
                    FROM catalog_annotations
                ), contamination AS (
                    SELECT segment_id, GROUP_CONCAT(DISTINCT kind) AS kinds
                    FROM catalog_contamination_ranges GROUP BY segment_id
                )
                SELECT s.*, a.description, a.characters_json, a.actions_json,
                       a.scene_json, a.objects_json, a.facts_json, a.shot_type,
                       m.subject_medium, m.text_ratio, m.text_block_count,
                       COALESCE(c.kinds, '') AS contamination_kinds
                FROM catalog_segments s
                LEFT JOIN effective a ON a.segment_id=s.id AND a.rn=1
                LEFT JOIN catalog_segment_media_types m ON m.segment_id=s.id
                LEFT JOIN contamination c ON c.segment_id=s.id
                WHERE s.video_id=? ORDER BY s.start_ms,s.end_ms,s.id
                """,
                (str(video_id),),
            ).fetchall()
            connection.execute(
                "DELETE FROM catalog_semantic_span_segments WHERE span_id IN "
                "(SELECT id FROM catalog_semantic_spans WHERE video_id=?)",
                (str(video_id),),
            )
            connection.execute(
                "DELETE FROM catalog_semantic_spans WHERE video_id=?", (str(video_id),)
            )

            prepared: list[dict[str, object]] = []
            severe_tokens = ("black", "transition", "blur", "occlusion", "copyright")
            for row in rows:
                medium = str(row["subject_medium"] or "scene")
                contamination = str(row["contamination_kinds"] or "").casefold()
                blocked = medium in {"title_card", "screen_capture", "technical_chart"} or any(
                    token in contamination for token in severe_tokens
                )
                text_heavy = (
                    not blocked and (
                        (row["text_ratio"] is not None and row["text_ratio"] > 0.30)
                        or (row["text_block_count"] is not None and row["text_block_count"] >= 4)
                        or "text" in contamination or "subtitle" in contamination
                    )
                )
                values = [str(row["description"] or ""), str(row["shot_type"] or "")]
                for column in ("characters_json", "actions_json", "scene_json", "objects_json"):
                    try:
                        values.extend(str(value) for value in json.loads(row[column] or "[]"))
                    except (TypeError, ValueError):
                        pass
                text = " ".join(value for value in values if value)
                prepared.append({
                    "row": row,
                    "features": self._span_features(text),
                    "summary": str(row["description"] or ""),
                    "subjects": json.loads(row["characters_json"] or "[]"),
                    "actions": json.loads(row["actions_json"] or "[]"),
                    "scenes": json.loads(row["scene_json"] or "[]"),
                    "objects": json.loads(row["objects_json"] or "[]"),
                    "facts": json.loads(row["facts_json"] or "[]"),
                    "presentation_type": str(row["shot_type"] or "") or None,
                    "pollution": "blocked" if blocked else "text_heavy" if text_heavy else "clean",
                })

            groups: list[list[dict[str, object]]] = []
            current: list[dict[str, object]] = []
            for item in prepared:
                row = item["row"]
                assert isinstance(row, sqlite3.Row)
                if not current:
                    current = [item]
                    continue
                previous = current[-1]["row"]
                assert isinstance(previous, sqlite3.Row)
                current_start = current[0]["row"]["start_ms"]  # type: ignore[index]
                combined_duration = row["end_ms"] - current_start
                left = set().union(*(entry["features"] for entry in current))
                right = item["features"]
                assert isinstance(right, set)
                similarity = len(left & right) / max(1, min(len(left), len(right)))
                short_side = min(
                    previous["end_ms"] - previous["start_ms"], row["end_ms"] - row["start_ms"]
                ) < 2_500
                merge = (
                    current[-1]["pollution"] != "blocked"
                    and item["pollution"] != "blocked"
                    and 0 <= row["start_ms"] - previous["end_ms"] <= 750
                    and combined_duration <= maximum_span_ms
                    and (similarity >= 0.08 or short_side)
                )
                if merge:
                    current.append(item)
                else:
                    groups.append(current)
                    current = [item]
            if current:
                groups.append(current)

            created_at = datetime.now(UTC).isoformat()
            for group in groups:
                first = group[0]["row"]
                last = group[-1]["row"]
                assert isinstance(first, sqlite3.Row) and isinstance(last, sqlite3.Row)
                start_ms, end_ms = int(first["start_ms"]), int(last["end_ms"])
                pollution = (
                    "blocked" if any(item["pollution"] == "blocked" for item in group)
                    else "text_heavy" if any(item["pollution"] == "text_heavy" for item in group)
                    else "clean"
                )
                summaries = list(dict.fromkeys(
                    str(item["summary"]).strip() for item in group if str(item["summary"]).strip()
                ))
                def aggregate(field: str) -> list[object]:
                    values: list[object] = []
                    seen: set[str] = set()
                    for entry in group:
                        for value in entry[field]:  # type: ignore[index]
                            identity = json.dumps(value, ensure_ascii=False, sort_keys=True)
                            if identity not in seen:
                                seen.add(identity)
                                values.append(value)
                    return values

                subjects = aggregate("subjects")
                actions = aggregate("actions")
                scenes = aggregate("scenes")
                objects = aggregate("objects")
                facts = aggregate("facts")
                anchors = [
                    [int(entry["row"]["start_ms"]), int(entry["row"]["end_ms"])]  # type: ignore[index]
                    for entry in group
                ]
                presentation_types = [
                    str(entry["presentation_type"])
                    for entry in group if entry["presentation_type"]
                ]
                presentation_type = max(
                    set(presentation_types), key=presentation_types.count,
                ) if presentation_types else None
                span_id = uuid5(
                    NAMESPACE_URL, f"clipatlas:semantic-span:{video_id}:{start_ms}:{end_ms}"
                )
                continuity_key = f"{video_id}:{start_ms}:{end_ms}"
                connection.execute(
                    """INSERT INTO catalog_semantic_spans (
                        id,video_id,start_ms,end_ms,safe_start_ms,safe_end_ms,summary,
                        subjects_json,actions_json,scenes_json,objects_json,facts_json,
                        anchor_ranges_json,continuity_key,visual_family,presentation_type,
                        pollution_level,created_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (str(span_id), str(video_id), start_ms, end_ms, start_ms, end_ms,
                     "；".join(summaries[:3])[:1000],
                     json.dumps(subjects, ensure_ascii=False),
                     json.dumps(actions, ensure_ascii=False),
                     json.dumps(scenes, ensure_ascii=False),
                     json.dumps(objects, ensure_ascii=False),
                     json.dumps(facts, ensure_ascii=False),
                     json.dumps(anchors), continuity_key, None, presentation_type,
                     pollution, created_at),
                )
                for ordinal, item in enumerate(group):
                    segment = item["row"]
                    assert isinstance(segment, sqlite3.Row)
                    connection.execute(
                        "INSERT INTO catalog_semantic_span_segments VALUES(?,?,?)",
                        (str(span_id), segment["id"], ordinal),
                    )
        return len(groups)

    @staticmethod
    def _semantic_span_from_row(row: sqlite3.Row) -> SemanticSpan:
        return SemanticSpan(
            id=UUID(row["id"]), video_id=UUID(row["video_id"]),
            start_ms=row["start_ms"], end_ms=row["end_ms"],
            safe_start_ms=row["safe_start_ms"], safe_end_ms=row["safe_end_ms"],
            summary=row["summary"], continuity_key=row["continuity_key"],
            subjects=json.loads(row["subjects_json"] or "[]"),
            actions=json.loads(row["actions_json"] or "[]"),
            scenes=json.loads(row["scenes_json"] or "[]"),
            objects=json.loads(row["objects_json"] or "[]"),
            facts=json.loads(row["facts_json"] or "[]"),
            anchor_ranges=json.loads(row["anchor_ranges_json"] or "[]"),
            visual_family=row["visual_family"],
            presentation_type=row["presentation_type"],
            pollution_level=row["pollution_level"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def get_semantic_span_for_segment(self, segment_id: UUID) -> SemanticSpan | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT sp.* FROM catalog_semantic_spans sp
                JOIN catalog_semantic_span_segments ss ON ss.span_id=sp.id
                WHERE ss.segment_id=? LIMIT 1
                """,
                (str(segment_id),),
            ).fetchone()
            if row is None:
                segment = connection.execute(
                    "SELECT video_id FROM catalog_segments WHERE id=?", (str(segment_id),)
                ).fetchone()
        if row is not None:
            return self._semantic_span_from_row(row)
        if segment is None:
            return None
        self.rebuild_semantic_spans(UUID(segment["video_id"]))
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT sp.* FROM catalog_semantic_spans sp
                JOIN catalog_semantic_span_segments ss ON ss.span_id=sp.id
                WHERE ss.segment_id=? LIMIT 1
                """,
                (str(segment_id),),
            ).fetchone()
        return self._semantic_span_from_row(row) if row is not None else None

    def list_semantic_spans(
        self, video_id: UUID, *, limit: int, offset: int = 0,
    ) -> list[SemanticSpan]:
        if limit < 1 or offset < 0:
            raise ValueError("invalid pagination")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM catalog_semantic_spans
                WHERE video_id=? ORDER BY start_ms,end_ms,id LIMIT ? OFFSET ?
                """,
                (str(video_id), limit, offset),
            ).fetchall()
        return [self._semantic_span_from_row(row) for row in rows]

    def expand_segment_window(
        self, segment_id: UUID, target_ms: int,
    ) -> tuple[int, int] | None:
        if target_ms <= 0:
            return None
        segment = self.get_segment(segment_id)
        span = self.get_semantic_span_for_segment(segment_id)
        if segment is None or span is None or span.pollution_level == "blocked":
            return None
        available = span.safe_end_ms - span.safe_start_ms
        if available <= segment.end_ms - segment.start_ms:
            return segment.start_ms, segment.end_ms
        wanted = min(target_ms, available)
        anchor = (segment.start_ms + segment.end_ms) // 2
        start = max(span.safe_start_ms, min(anchor - wanted // 2, span.safe_end_ms - wanted))
        return start, start + wanted

    def count_segments(self, video_id: UUID) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM catalog_segments WHERE video_id = ?",
                (str(video_id),),
            ).fetchone()
        return int(row["count"] if row is not None else 0)

    def count_missing_catalog_data(self, video_id: UUID) -> int:
        """Count segments still missing an AI annotation or a media-type row.

        Used by 增补解析 (supplement) to decide whether a completed video
        needs another incremental pass. Returns 0 when nothing is missing.
        """
        with self._connect() as connection:
            segs = connection.execute(
                "SELECT COUNT(*) FROM catalog_segments WHERE video_id = ?",
                (str(video_id),),
            ).fetchone()[0]
            anns = connection.execute(
                """
                SELECT COUNT(DISTINCT s.id) FROM catalog_segments s
                JOIN catalog_annotations a ON a.segment_id = s.id
                WHERE s.video_id = ?
                """,
                (str(video_id),),
            ).fetchone()[0]
            mts = connection.execute(
                """
                SELECT COUNT(DISTINCT s.id) FROM catalog_segments s
                JOIN catalog_segment_media_types m ON m.segment_id = s.id
                WHERE s.video_id = ?
                """,
                (str(video_id),),
            ).fetchone()[0]
        missing = max(0, int(segs) - int(anns)) + max(0, int(segs) - int(mts))
        return missing

    def list_segments(
        self,
        video_id: UUID,
        *,
        limit: int,
        offset: int,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> list[VideoSegment]:
        if limit < 1:
            raise ValueError("limit must be positive")
        if offset < 0:
            raise ValueError("offset must be non-negative")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM catalog_segments
                WHERE video_id = ?
                  AND (? IS NULL OR end_ms > ?)
                  AND (? IS NULL OR start_ms < ?)
                ORDER BY start_ms, end_ms, id
                LIMIT ? OFFSET ?
                """,
                (str(video_id), start_ms, start_ms, end_ms, end_ms, limit, offset),
            ).fetchall()
        return [
            VideoSegment(
                id=UUID(row["id"]),
                video_id=UUID(row["video_id"]),
                start_ms=row["start_ms"],
                end_ms=row["end_ms"],
                source=SegmentSource(row["source"]),
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    def get_video_annotation_stats(self, video_id: UUID) -> VideoAnnotationStats:
        segments_total = self.count_segments(video_id)
        with self._connect() as connection:
            row = connection.execute(
                """
                WITH ranked AS (
                    SELECT
                        a.*,
                        ROW_NUMBER() OVER (
                            PARTITION BY a.segment_id
                            ORDER BY
                                CASE WHEN a.origin = ? THEN 0 ELSE 1 END,
                                a.revision DESC,
                                a.created_at DESC,
                                a.rowid DESC
                        ) AS rn
                    FROM catalog_annotations AS a
                    JOIN catalog_segments AS s ON s.id = a.segment_id
                    WHERE s.video_id = ?
                )
                SELECT
                    COUNT(*) AS annotated,
                    COALESCE(SUM(CASE WHEN origin = ? THEN 1 ELSE 0 END), 0) AS ai_effective,
                    COALESCE(SUM(CASE WHEN origin = ? THEN 1 ELSE 0 END), 0) AS human_effective,
                    COALESCE(SUM(CASE WHEN locked = 1 THEN 1 ELSE 0 END), 0) AS locked
                FROM ranked
                WHERE rn = 1
                """,
                (
                    AnnotationOrigin.HUMAN.value,
                    str(video_id),
                    AnnotationOrigin.AI.value,
                    AnnotationOrigin.HUMAN.value,
                ),
            ).fetchone()
        return VideoAnnotationStats(
            segments_total=segments_total,
            annotated=int(row["annotated"] if row is not None else 0),
            ai_effective=int(row["ai_effective"] if row is not None else 0),
            human_effective=int(row["human_effective"] if row is not None else 0),
            locked=int(row["locked"] if row is not None else 0),
        )

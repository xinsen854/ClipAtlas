import sqlite3
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from clipatlas.library.fingerprint import canonicalize_path
from clipatlas.speech.batches import BatchSummary, NarrationBatch
from clipatlas.speech.models import (
    NarrationSourceMode,
    NarrationTrack,
    NarrationUnit,
    NarrationWordTiming,
    ProjectScript,
    SpeechProfile,
    utc_now,
)


class NarrationStore:
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
                CREATE TABLE IF NOT EXISTS narration_batches (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS project_scripts (
                    project_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS speech_profiles (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    locked INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_speech_profiles_project_locked_revision
                ON speech_profiles(project_id, locked, revision DESC, created_at DESC);

                CREATE TABLE IF NOT EXISTS narration_tracks (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_narration_tracks_project_revision
                ON narration_tracks(project_id, revision DESC, created_at DESC);

                CREATE TABLE IF NOT EXISTS narration_units (
                    id TEXT PRIMARY KEY,
                    track_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    text_hash TEXT NOT NULL,
                    completed INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE(track_id, sequence),
                    FOREIGN KEY(track_id) REFERENCES narration_tracks(id)
                );

                CREATE INDEX IF NOT EXISTS idx_narration_units_checkpoint
                ON narration_units(track_id, sequence, text_hash, completed);

                CREATE TABLE IF NOT EXISTS narration_word_timings (
                    unit_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY(unit_id, sequence),
                    FOREIGN KEY(unit_id) REFERENCES narration_units(id)
                );

                CREATE TABLE IF NOT EXISTS active_narration_tracks (
                    project_id TEXT PRIMARY KEY,
                    track_id TEXT NOT NULL,
                    FOREIGN KEY(track_id) REFERENCES narration_tracks(id)
                );
                """
            )

    def save_batch(self, batch: NarrationBatch) -> None:
        batch.updated_at = utc_now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO narration_batches VALUES (?, ?, ?, ?) ON CONFLICT(id) "
                "DO UPDATE SET payload_json=excluded.payload_json",
                (str(batch.id), str(batch.project_id), batch.created_at.isoformat(), batch.model_dump_json()),
            )

    def get_batch(self, batch_id: UUID) -> NarrationBatch | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM narration_batches WHERE id=?", (str(batch_id),),
            ).fetchone()
        return NarrationBatch.model_validate_json(row[0]) if row is not None else None

    def list_batches(self, project_id: UUID, *, limit: int = 20, offset: int = 0) -> list[BatchSummary]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, project_id, created_at, json_extract(payload_json, '$.name') AS name, "
                "json_array_length(payload_json, '$.entries') AS entry_count "
                "FROM narration_batches WHERE project_id=? ORDER BY created_at DESC, id "
                "LIMIT ? OFFSET ?", (str(project_id), limit, offset),
            ).fetchall()
        return [BatchSummary(**dict(row)) for row in rows]

    def get_project_script(self, project_id: UUID) -> ProjectScript | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM project_scripts WHERE project_id=?", (str(project_id),),
            ).fetchone()
        return ProjectScript.model_validate_json(row[0]) if row is not None else None

    def save_project_script(self, project_id: UUID, text: str) -> ProjectScript:
        script = ProjectScript(
            project_id=project_id, text=text,
            script_hash=sha256(text.encode()).hexdigest(), updated_at=utc_now(),
        )
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO project_scripts VALUES (?, ?) ON CONFLICT(project_id) "
                "DO UPDATE SET payload_json=excluded.payload_json",
                (str(project_id), script.model_dump_json()),
            )
        return script

    def save_profile(self, profile: SpeechProfile) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO speech_profiles (
                    id, project_id, revision, locked, created_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    project_id = excluded.project_id,
                    revision = excluded.revision,
                    locked = excluded.locked,
                    created_at = excluded.created_at,
                    payload_json = excluded.payload_json
                """,
                (
                    str(profile.id),
                    str(profile.project_id),
                    profile.revision,
                    int(profile.locked),
                    profile.created_at.isoformat(),
                    profile.model_dump_json(),
                ),
            )

    def get_profile(self, profile_id: UUID) -> SpeechProfile | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM speech_profiles WHERE id = ?",
                (str(profile_id),),
            ).fetchone()
        return SpeechProfile.model_validate_json(row["payload_json"]) if row is not None else None

    def list_profiles(self, project_id: UUID) -> list[SpeechProfile]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload_json FROM speech_profiles
                WHERE project_id = ?
                ORDER BY revision DESC, created_at DESC, rowid DESC
                """,
                (str(project_id),),
            ).fetchall()
        return [SpeechProfile.model_validate_json(row["payload_json"]) for row in rows]

    def get_latest_locked_profile(self, project_id: UUID) -> SpeechProfile | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM speech_profiles
                WHERE project_id = ? AND locked = 1
                ORDER BY revision DESC, created_at DESC, rowid DESC
                LIMIT 1
                """,
                (str(project_id),),
            ).fetchone()
        return SpeechProfile.model_validate_json(row["payload_json"]) if row is not None else None

    def save_track(self, track: NarrationTrack) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO narration_tracks (
                    id, project_id, revision, created_at, payload_json
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    project_id = excluded.project_id,
                    revision = excluded.revision,
                    created_at = excluded.created_at,
                    payload_json = excluded.payload_json
                """,
                (
                    str(track.id),
                    str(track.project_id),
                    track.revision,
                    track.created_at.isoformat(),
                    track.model_dump_json(),
                ),
            )

    def get_track(self, track_id: UUID) -> NarrationTrack | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM narration_tracks WHERE id = ?",
                (str(track_id),),
            ).fetchone()
        return NarrationTrack.model_validate_json(row["payload_json"]) if row is not None else None

    def save_track_snapshot(self, track: NarrationTrack, units: list[NarrationUnit]) -> None:
        """Publish a complete new alignment revision atomically; never overwrite the source."""
        if not units or any(unit.track_id != track.id for unit in units):
            raise ValueError("Snapshot units must belong to the new track")
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO narration_tracks VALUES (?, ?, ?, ?, ?)",
                (str(track.id), str(track.project_id), track.revision,
                 track.created_at.isoformat(), track.model_dump_json()),
            )
            connection.executemany(
                "INSERT INTO narration_units VALUES (?, ?, ?, ?, ?, ?)",
                [(str(u.id), str(u.track_id), u.sequence, u.text_hash, 0, u.model_dump_json())
                 for u in units],
            )

    def list_tracks(self, project_id: UUID) -> list[NarrationTrack]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload_json FROM narration_tracks
                WHERE project_id = ?
                ORDER BY revision DESC, created_at DESC, rowid DESC
                """,
                (str(project_id),),
            ).fetchall()
        return [NarrationTrack.model_validate_json(row["payload_json"]) for row in rows]

    def find_resumable_tts_track(
        self,
        project_id: UUID,
        script_hash: str,
        speech_profile_id: UUID,
        rule_pack_revision: int | None = None,
    ) -> NarrationTrack | None:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload_json FROM narration_tracks
                WHERE project_id = ?
                ORDER BY revision DESC, created_at DESC, rowid DESC
                """,
                (str(project_id),),
            ).fetchall()
        for row in rows:
            track = NarrationTrack.model_validate_json(row["payload_json"])
            if (
                track.source_mode == NarrationSourceMode.TTS
                and track.script_hash == script_hash
                and track.speech_profile_id == speech_profile_id
                and track.rule_pack_revision == rule_pack_revision
                and track.audio_uri is None
            ):
                return track
        return None

    def next_track_revision(self, project_id: UUID) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT MAX(revision) AS revision FROM narration_tracks WHERE project_id = ?",
                (str(project_id),),
            ).fetchone()
        current = row["revision"] if row is not None else None
        return int(current or 0) + 1

    def activate_track(self, project_id: UUID, track_id: UUID) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT project_id FROM narration_tracks WHERE id = ?",
                (str(track_id),),
            ).fetchone()
            if row is None or row["project_id"] != str(project_id):
                return False
            connection.execute(
                """
                INSERT INTO active_narration_tracks (project_id, track_id)
                VALUES (?, ?)
                ON CONFLICT(project_id) DO UPDATE SET track_id = excluded.track_id
                """,
                (str(project_id), str(track_id)),
            )
        return True

    def get_active_track(self, project_id: UUID) -> NarrationTrack | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT t.payload_json
                FROM narration_tracks AS t
                LEFT JOIN active_narration_tracks AS a
                    ON a.project_id = t.project_id AND a.track_id = t.id
                WHERE t.project_id = ?
                ORDER BY CASE WHEN a.track_id IS NOT NULL THEN 0 ELSE 1 END,
                         t.revision DESC,
                         t.created_at DESC
                LIMIT 1
                """,
                (str(project_id),),
            ).fetchone()
        return NarrationTrack.model_validate_json(row["payload_json"]) if row is not None else None

    def save_unit(self, unit: NarrationUnit) -> None:
        completed = unit.start_ms is not None and unit.end_ms is not None and unit.audio_uri is not None
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO narration_units (
                    id, track_id, sequence, text_hash, completed, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    track_id = excluded.track_id,
                    sequence = excluded.sequence,
                    text_hash = excluded.text_hash,
                    completed = excluded.completed,
                    payload_json = excluded.payload_json
                """,
                (
                    str(unit.id),
                    str(unit.track_id),
                    unit.sequence,
                    unit.text_hash,
                    int(completed),
                    unit.model_dump_json(),
                ),
            )

    def list_units(self, track_id: UUID) -> list[NarrationUnit]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload_json FROM narration_units
                WHERE track_id = ?
                ORDER BY sequence, rowid
                """,
                (str(track_id),),
            ).fetchall()
        return [NarrationUnit.model_validate_json(row["payload_json"]) for row in rows]

    def get_completed_unit(
        self,
        track_id: UUID,
        sequence: int,
        text_hash: str,
    ) -> NarrationUnit | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM narration_units
                WHERE track_id = ? AND sequence = ? AND text_hash = ? AND completed = 1
                LIMIT 1
                """,
                (str(track_id), sequence, text_hash),
            ).fetchone()
        return NarrationUnit.model_validate_json(row["payload_json"]) if row is not None else None

    def save_word_timings(self, items: list[NarrationWordTiming]) -> None:
        with self._connect() as connection:
            for item in items:
                connection.execute(
                    """
                    INSERT INTO narration_word_timings (unit_id, sequence, payload_json)
                    VALUES (?, ?, ?)
                    ON CONFLICT(unit_id, sequence) DO UPDATE SET
                        payload_json = excluded.payload_json
                    """,
                    (str(item.unit_id), item.sequence, item.model_dump_json()),
                )

    def list_word_timings(self, track_id: UUID) -> list[NarrationWordTiming]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT w.payload_json
                FROM narration_word_timings AS w
                JOIN narration_units AS u ON u.id = w.unit_id
                WHERE u.track_id = ?
                ORDER BY u.sequence, w.sequence
                """,
                (str(track_id),),
            ).fetchall()
        return [NarrationWordTiming.model_validate_json(row["payload_json"]) for row in rows]

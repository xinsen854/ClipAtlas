"""Explicit user-requested reset of the shared library's derived analysis."""

import os
import shutil
import sqlite3
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname
from uuid import UUID, uuid4

from pydantic import BaseModel

from clipatlas.domain.models import utc_now


class LibraryResetResult(BaseModel):
    items_reset: int
    cache_directories_removed: int
    backup_path: str
    warning: str | None = None


class LibraryMaintenance:
    def __init__(self, db_path: Path, cache_root: Path) -> None:
        self.db_path = db_path.resolve()
        self.cache_root = cache_root.absolute()

    def reset_analysis(self) -> LibraryResetResult:
        root = self.cache_root
        if root.is_symlink() or root.is_junction() or root.resolve() != root:
            raise ValueError("Cache root must not traverse a symbolic link or junction")
        if root == root.parent or self.db_path.is_relative_to(root):
            raise ValueError("Unsafe library cache root")
        token = uuid4().hex
        backup = self.db_path.with_name(self.db_path.name + f".bak-reset-{token}")
        with sqlite3.connect(self.db_path) as source, sqlite3.connect(backup) as destination:
            source.backup(destination)

        connection = sqlite3.connect(self.db_path, timeout=10)
        moved: list[tuple[Path, Path]] = []
        holding = root / f".reset-{token}"
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            items = connection.execute("SELECT id, source_path FROM library_items").fetchall()
            if connection.execute(
                "SELECT 1 FROM library_items WHERE status IN "
                "('PROBING','SCENE_DETECTION','FRAME_EXTRACTION') LIMIT 1"
            ).fetchone():
                raise ValueError("A library item is still being processed")
            targets = [root / name for name in ("video-chunks", "asr", "ocr")]
            for item_id, _ in items:
                targets.append(root / str(UUID(item_id)) / "frames")
            sources = [Path(path).resolve() for _, path in items]
            for (uri,) in connection.execute("SELECT source_uri FROM catalog_videos"):
                parsed = urlparse(uri)
                if parsed.scheme == "file":
                    sources.append(Path(url2pathname(parsed.path)).resolve())
            for target in targets:
                resolved = target.resolve()
                if not resolved.is_relative_to(root) or any(
                    source.is_relative_to(resolved) for source in sources
                ):
                    raise ValueError("Refusing to remove a source-media path")
                if not target.exists():
                    continue
                if not target.is_dir():
                    raise ValueError("Expected a cache directory")
                # Validate every node before any move/delete; never follow links.
                for directory, subdirs, files in os.walk(target, followlinks=False):
                    for entry in [Path(directory), *(Path(directory) / n for n in subdirs + files)]:
                        if entry.is_symlink() or entry.is_junction():
                            raise ValueError("Cache contains a symbolic link or junction")
            for target in targets:
                if target.exists():
                    holding.mkdir(exist_ok=True)
                    saved = holding / str(len(moved))
                    target.rename(saved)
                    moved.append((target, saved))
            for table in (
                "catalog_embeddings", "catalog_annotations", "catalog_segment_frames",
                "catalog_video_chunk_embeddings", "catalog_video_chunk_checkpoints",
                "catalog_asr_chunks", "catalog_ocr_samples", "catalog_preparation_checkpoints",
                "catalog_segments", "catalog_videos",
            ):
                connection.execute(f"DELETE FROM {table}")
            connection.execute(
                "UPDATE library_items SET video_id=NULL, processed_fingerprint=NULL, "
                "status=CASE WHEN status='MISSING' THEN 'MISSING' ELSE 'QUEUED' END, "
                "attempts=0, last_error=NULL, updated_at=?", (utc_now().isoformat(),),
            )
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("Foreign key check failed; reset rolled back")
            connection.commit()
        except BaseException:
            connection.rollback()
            for target, saved in reversed(moved):
                saved.rename(target)
            if holding.exists():
                holding.rmdir()
            raise
        finally:
            connection.close()
        warning = None
        if holding.exists():
            try:
                # holding was generated here and has already been checked beneath cache_root.
                shutil.rmtree(holding)
            except OSError:
                warning = f"解析已重置，但部分旧缓存暂未移除：{holding}"
        return LibraryResetResult(
            items_reset=len(items), cache_directories_removed=len(moved) if warning is None else 0,
            backup_path=str(backup), warning=warning,
        )

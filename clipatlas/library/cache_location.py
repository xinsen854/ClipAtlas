"""Move existing cache and frame references together, without rebuilding indexes."""

import shutil
import sqlite3
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname
from uuid import uuid4

from pydantic import BaseModel

from clipatlas.managed_files import remove_tree, validate_tree
from clipatlas.settings.models import SettingsPatch
from clipatlas.settings.store import SettingsStore


class CacheMoveResult(BaseModel):
    previous_path: str
    path: str
    files_moved: int
    backup_path: str | None = None
    restart_required: bool
    warning: str | None = None


def move_library_cache(db_path: Path, old_root: Path, destination: Path,
                       settings: SettingsStore) -> CacheMoveResult:
    old_root = old_root.absolute()
    destination = destination.expanduser().absolute()
    if destination == old_root:
        return CacheMoveResult(previous_path=str(old_root), path=str(old_root),
                               files_moved=0, restart_required=False)
    if settings.public_snapshot().library_cache_root.source == 'environment':
        raise ValueError('缓存位置由环境变量管理，请先移除该环境变量再通过页面迁移')
    validate_tree(old_root, old_root)
    validate_tree(destination, destination)
    if (old_root.is_relative_to(destination) or destination.is_relative_to(old_root)
            or db_path.resolve().is_relative_to(destination)):
        raise ValueError('新旧缓存目录不能互相包含，也不能包含数据库')
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('请选择一个空目录，避免覆盖其他文件')
    with sqlite3.connect(db_path) as c:
        if c.execute("SELECT 1 FROM library_items WHERE status IN ('PROBING','SCENE_DETECTION','FRAME_EXTRACTION') LIMIT 1").fetchone():
            raise ValueError('素材正在处理，请完成后再迁移缓存')
        sources = [Path(row[0]).resolve() for row in c.execute('SELECT source_path FROM library_items')]
        for (uri,) in c.execute('SELECT source_uri FROM catalog_videos'):
            parsed = urlparse(uri)
            if parsed.scheme == 'file':
                sources.append(Path(url2pathname(parsed.path)).resolve())
        if any(source.is_relative_to(old_root) or source.is_relative_to(destination) for source in sources):
            raise ValueError('缓存目录包含原始素材，拒绝迁移或删除原文件')
    token = uuid4().hex
    stage = destination.parent/f'.clipatlas-cache-move-{token}'
    validate_tree(destination.parent, stage)
    destination.parent.mkdir(parents=True, exist_ok=True)
    backup = db_path.with_name(db_path.name+f'.bak-cache-move-{token}')
    with sqlite3.connect(db_path) as src, sqlite3.connect(backup) as dst:
        src.backup(dst)
    old_setting = settings.read_persisted().library_cache_root
    moved = saved_setting = False
    files = 0
    c = sqlite3.connect(db_path, timeout=10)
    try:
        if old_root.exists():
            shutil.copytree(old_root, stage)
            for source in old_root.rglob('*'):
                if source.is_file():
                    copied = stage/source.relative_to(old_root)
                    if not copied.is_file() or copied.stat().st_size != source.stat().st_size:
                        raise OSError('缓存复制校验失败')
                    files += 1
        else:
            stage.mkdir()
        validate_tree(destination.parent, stage)
        if destination.exists():
            destination.rmdir()  # only an empty user-selected destination can be replaced
        stage.rename(destination)
        moved = True
        c.execute('BEGIN IMMEDIATE')
        rows = c.execute('SELECT rowid,uri FROM catalog_segment_frames').fetchall()
        for rowid, uri in rows:
            parsed = urlparse(uri)
            if parsed.scheme != 'file' or parsed.netloc not in ('', 'localhost'):
                continue
            path = Path(url2pathname(parsed.path)).resolve()
            if path.is_relative_to(old_root):
                replacement = (destination/path.relative_to(old_root)).as_uri()
                c.execute('UPDATE catalog_segment_frames SET uri=? WHERE rowid=?', (replacement,rowid))
        if c.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('缓存迁移后的外键检查失败')
        settings.update(SettingsPatch(library_cache_root=str(destination)))
        saved_setting = True
        c.commit()
    except BaseException:
        c.rollback()
        if saved_setting:
            settings.update(SettingsPatch(library_cache_root=old_setting))
        if moved:
            remove_tree(destination.parent, destination)
        elif stage.exists():
            remove_tree(destination.parent, stage)
        raise
    finally:
        c.close()
    warning = None
    try:
        remove_tree(old_root, old_root)
    except (OSError, ValueError):
        warning = f'迁移成功，但旧目录部分文件被占用，请重启后检查：{old_root}'
    return CacheMoveResult(previous_path=str(old_root), path=str(destination),
                           files_moved=files, backup_path=str(backup),
                           restart_required=True, warning=warning)

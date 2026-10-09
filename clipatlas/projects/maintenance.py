"""Remove a project's own data, leaving the shared material library untouched."""

import json
import sqlite3
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from clipatlas.managed_files import remove_tree, validate_tree


class ProjectDeletionPreview(BaseModel):
    project_id: UUID
    name: str
    narrations: int
    plans: int
    batches: int
    directories: list[str]
    warnings: list[str] = Field(default_factory=list)


class ProjectDeletionResult(ProjectDeletionPreview):
    backup_directory: str
    plan_ids: list[UUID]


class ProjectMaintenance:
    def __init__(self, *, project_db: Path, narration_db: Path, roughcut_db: Path,
                 rules_db: Path, narration_root: Path, export_root: Path,
                 library_db: Path | None = None) -> None:
        self.databases = {name: path.resolve() for name, path in {
            'projects': project_db, 'narration': narration_db,
            'roughcut': roughcut_db, 'rules': rules_db,
        }.items()}
        self.narration_root = narration_root.absolute()
        self.export_root = export_root.absolute()
        self.library_db = library_db

    def _connect(self) -> tuple[sqlite3.Connection, dict[str, str]]:
        c = sqlite3.connect(self.databases['projects'], timeout=10)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        aliases = {}
        seen = {self.databases['projects']: 'main'}
        for name, path in self.databases.items():
            if path not in seen:
                alias = f'db{len(seen)}'
                c.execute(f'ATTACH DATABASE ? AS {alias}', (str(path),))
                seen[path] = alias
            aliases[name] = seen[path]
        return c, aliases

    def _preview(self, c: sqlite3.Connection, a: dict[str, str], project_id: UUID
                 ) -> tuple[ProjectDeletionPreview, list[tuple[Path, Path]], list[UUID]]:
        key = str(project_id)
        project = c.execute('SELECT name FROM projects WHERE id=?', (key,)).fetchone()
        if project is None:
            raise LookupError('project not found')
        tracks = c.execute(f"SELECT id,payload_json FROM {a['narration']}.narration_tracks WHERE project_id=?", (key,)).fetchall()
        plans = [UUID(r[0]) for r in c.execute(f"SELECT id FROM {a['roughcut']}.rough_cut_plans WHERE project_id=?", (key,))]
        batches = c.execute(f"SELECT count(*) FROM {a['narration']}.narration_batches WHERE project_id=?", (key,)).fetchone()[0]
        candidates = {(self.narration_root, self.narration_root/key),
                      (self.export_root, self.export_root/key)}
        for track in tracks:
            candidates.add((self.narration_root, self.narration_root/str(UUID(track['id']))))
        other_audio = []
        for row in c.execute(f"SELECT payload_json FROM {a['narration']}.narration_tracks WHERE project_id<>?", (key,)):
            uri = json.loads(row[0]).get('audio_uri')
            if uri:
                parsed = urlparse(uri)
                if parsed.scheme == 'file':
                    other_audio.append(Path(url2pathname(parsed.path)).resolve())
        targets = []
        warnings = []
        original_media = []
        if self.library_db is not None:
            with sqlite3.connect(self.library_db.resolve().as_uri()+'?mode=ro', uri=True) as library:
                original_media = [Path(r[0]).resolve() for r in library.execute('SELECT source_path FROM library_items')]
                for (uri,) in library.execute('SELECT source_uri FROM catalog_videos'):
                    parsed = urlparse(uri)
                    if parsed.scheme == 'file':
                        original_media.append(Path(url2pathname(parsed.path)).resolve())
        for root, target in sorted(candidates, key=lambda pair: str(pair[1])):
            validate_tree(root, target)
            if any(database.is_relative_to(target) for database in self.databases.values()):
                raise ValueError('Refusing to delete a database directory')
            if any(path.is_relative_to(target) for path in original_media):
                raise ValueError('项目目录内包含素材库原视频，拒绝删除原始素材')
            if any(path.is_relative_to(target) for path in other_audio):
                warnings.append(f'文件被其他项目引用，保留：{target}')
                continue
            if target.exists():
                targets.append((root, target))
        return ProjectDeletionPreview(project_id=project_id, name=project['name'],
            narrations=len(tracks), plans=len(plans), batches=batches,
            directories=[str(target) for _,target in targets], warnings=warnings), targets, plans

    def preview(self, project_id: UUID) -> ProjectDeletionPreview:
        c, aliases = self._connect()
        try:
            return self._preview(c, aliases, project_id)[0]
        finally:
            c.close()

    def delete(self, project_id: UUID) -> ProjectDeletionResult:
        token = uuid4().hex
        backup = self.databases['projects'].parent/'project-backups'/f'{project_id}-{token}'
        backup.mkdir(parents=True)
        for name, path in self.databases.items():
            with sqlite3.connect(path) as src, sqlite3.connect(backup/f'{name}.sqlite3') as dst:
                src.backup(dst)
        c, a = self._connect()
        moved: list[tuple[Path, Path, Path]] = []
        try:
            c.execute('BEGIN IMMEDIATE')
            preview, targets, plans = self._preview(c, a, project_id)
            for root, target in targets:
                holding = root/f'.delete-project-{token}-{len(moved)}'
                validate_tree(root, target)
                validate_tree(root, holding)
                target.rename(holding)
                moved.append((root, target, holding))
            key = str(project_id)
            n = a['narration']
            owned = f"SELECT id FROM {n}.narration_tracks WHERE project_id=?"
            units = f"SELECT id FROM {n}.narration_units WHERE track_id IN ({owned})"
            c.execute(f'DELETE FROM {n}.narration_word_timings WHERE unit_id IN ({units})', (key,))
            c.execute(f'DELETE FROM {n}.narration_units WHERE track_id IN ({owned})', (key,))
            for table in ['active_narration_tracks','narration_tracks','speech_profiles','project_scripts','narration_batches']:
                c.execute(f'DELETE FROM {n}.{table} WHERE project_id=?', (key,))
            for table in ['active_rough_cut_plans','rough_cut_plans']:
                c.execute(f"DELETE FROM {a['roughcut']}.{table} WHERE project_id=?", (key,))
            c.execute(f"DELETE FROM {a['rules']}.project_rule_packs WHERE project_id=?", (key,))
            c.execute('DELETE FROM projects WHERE id=?', (key,))
            for alias in set(a.values()):
                if c.execute(f'PRAGMA {alias}.foreign_key_check').fetchall():
                    raise ValueError('Project deletion would violate foreign keys')
            c.commit()
        except BaseException:
            c.rollback()
            for root, target, holding in reversed(moved):
                validate_tree(root, holding)
                validate_tree(root, target)
                holding.rename(target)
            raise
        finally:
            c.close()
        for root, _, holding in moved:
            try:
                remove_tree(root, holding)
            except (OSError, ValueError):
                preview.warnings.append(f'项目已删除，部分文件暂被占用，保留于：{holding}')
        return ProjectDeletionResult(**preview.model_dump(), backup_directory=str(backup), plan_ids=plans)

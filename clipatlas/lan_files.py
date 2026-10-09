"""Client-owned media directory index and conservative sampled-content matching."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import threading
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname

EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
SAMPLE_BYTES = 1024 * 1024


def source_path(uri: str) -> Path:
    parsed = urlsplit(uri)
    if parsed.scheme != "file" or parsed.netloc not in ("", "localhost"):
        raise ValueError("原素材不是本机文件")
    return Path(url2pathname(parsed.path)).resolve()


def fingerprint(path: Path) -> str:
    size = path.stat().st_size
    digest = hashlib.sha256(str(size).encode())
    with path.open("rb") as stream:
        for offset in sorted({0, max(0, size // 2 - SAMPLE_BYTES // 2), max(0, size - SAMPLE_BYTES)}):
            stream.seek(offset)
            digest.update(stream.read(SAMPLE_BYTES))
    return digest.hexdigest()


class LocalFiles:
    def __init__(self) -> None:
        self.root: Path | None = None
        self.files: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.hashes: dict[tuple[str, int, int], str] = {}

    def scan(self, value: str) -> dict:
        root = Path(value).expanduser().resolve()
        if not root.is_dir():
            raise ValueError("本地素材文件夹不存在或无法访问")
        files = {}
        skipped = 0
        def skip(_):
            nonlocal skipped
            skipped += 1
        for directory, dirs, names in os.walk(root, followlinks=False, onerror=skip):
            dirs[:] = [d for d in dirs if not (Path(directory) / d).is_symlink()
                       and not os.path.isjunction(Path(directory) / d)]
            for name in names:
                path = Path(directory) / name
                if path.suffix.lower() not in EXTENSIONS:
                    continue
                try:
                    resolved = path.resolve()
                    if not resolved.is_relative_to(root) or not resolved.is_file():
                        continue
                    stat = resolved.stat()
                    key = hashlib.sha256(str(resolved).encode()).hexdigest()
                    files[key] = {"id": key, "name": name, "path": str(resolved),
                                  "relative": str(resolved.relative_to(root)), "size": stat.st_size}
                except OSError:
                    skipped += 1
        with self.lock:
            self.root = root
            self.files = files
            self.hashes = {}
        return {"root": str(root), "count": len(files), "skipped": skipped}

    def status(self) -> dict:
        with self.lock:
            return {"root": str(self.root) if self.root else None, "count": len(self.files)}

    def get(self, key: str) -> Path:
        with self.lock:
            item = self.files.get(key)
            root = self.root
        if not item or root is None:
            raise ValueError("文件索引已变化，请刷新搜索结果")
        path = Path(item["path"]).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError("本地文件已移动或删除，请重新扫描文件夹")
        return path

    def match(self, metadata: dict) -> dict:
        with self.lock:
            entries = list(self.files.values())
            root = self.root
        if root is None:
            return {"status": "no-folder", "candidates": []}
        name = metadata["filename"].casefold()
        size = metadata.get("size")
        signature = metadata.get("fingerprint")
        candidates = []
        # Size narrows the search even if somebody renamed the local copy.
        pool = [x for x in entries if x["size"] == size] if size is not None else [
            x for x in entries if x["name"].casefold() == name]
        for item in pool:
            try:
                path = self.get(item["id"])
                if signature:
                    stat = path.stat()
                    cache_key = (str(path), stat.st_size, stat.st_mtime_ns)
                    with self.lock:
                        digest = self.hashes.get(cache_key)
                    if digest is None:
                        digest = fingerprint(path)
                        with self.lock:
                            self.hashes[cache_key] = digest
                    if digest != signature:
                        continue
                    verified = True
                else:
                    if item["name"].casefold() != name:
                        continue
                    verified = False
                candidates.append({**item, "verified": verified})
            except (OSError, ValueError):
                continue
        return {"status": "matched" if candidates else "missing", "candidates": candidates}

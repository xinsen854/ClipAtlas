from pathlib import Path

from clipatlas.library.fingerprint import canonicalize_path, fast_fingerprint
from clipatlas.library.models import LibraryItem, LibraryItemStatus, LibraryRoot, ScanReport
from clipatlas.library.store import LibraryStore

SUPPORTED_VIDEO_EXTENSIONS = frozenset({".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"})
_PAGE_SIZE = 500


class LocalFolderScanner:
    def __init__(self, store: LibraryStore) -> None:
        self._store = store

    def _known_items(self, root: LibraryRoot) -> list[LibraryItem]:
        items: list[LibraryItem] = []
        offset = 0
        while True:
            page = self._store.list_items(root_id=root.id, limit=_PAGE_SIZE, offset=offset)
            items.extend(page)
            if len(page) < _PAGE_SIZE:
                break
            offset += len(page)
        return items

    def scan_root(self, root: LibraryRoot) -> ScanReport:
        root_path = canonicalize_path(Path(root.path))
        known_items = self._known_items(root)

        if not root_path.is_dir():
            missing = 0
            for item in known_items:
                if item.status is not LibraryItemStatus.MISSING:
                    self._store.mark_missing(item.id)
                    missing += 1
            return ScanReport(missing=missing)

        candidates = root_path.rglob("*") if root.recursive else root_path.iterdir()
        observed: set[str] = set()
        discovered = 0
        changed = 0
        unchanged = 0

        for candidate in candidates:
            if candidate.is_symlink() or not candidate.is_file():
                continue
            if candidate.suffix.lower() not in SUPPORTED_VIDEO_EXTENSIONS:
                continue

            resolved = canonicalize_path(candidate)
            if not resolved.is_relative_to(root_path):
                continue

            stat = resolved.stat()
            fingerprint = fast_fingerprint(resolved, stat.st_size, stat.st_mtime_ns)
            outcome = self._store.save_observation(
                root_id=root.id,
                source_path=resolved,
                size_bytes=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
                fingerprint=fingerprint,
            )
            observed.add(str(resolved))

            if outcome == "discovered":
                discovered += 1
            elif outcome == "changed":
                changed += 1
            elif outcome in {"unchanged", "restored"}:
                unchanged += 1
            else:
                raise RuntimeError(f"unknown library observation outcome: {outcome}")

        missing = 0
        for item in known_items:
            if item.source_path not in observed and item.status is not LibraryItemStatus.MISSING:
                self._store.mark_missing(item.id)
                missing += 1

        return ScanReport(
            discovered=discovered,
            changed=changed,
            missing=missing,
            unchanged=unchanged,
        )

    def scan_all(self) -> ScanReport:
        total = ScanReport()
        for root in self._store.list_roots(enabled_only=True):
            total = total.add(self.scan_root(root))
        return total

import os
from pathlib import Path
from uuid import uuid4

import pytest

from clipatlas.library.models import LibraryItemStatus
from clipatlas.library.scanner import LocalFolderScanner
from clipatlas.library.store import LibraryStore


def _make_media_tree(root: Path) -> None:
    (root / "nested").mkdir(parents=True)
    (root / "one.mp4").write_bytes(b"one")
    (root / "TWO.MOV").write_bytes(b"two")
    (root / "ignore.txt").write_text("ignore")
    (root / "nested" / "three.mkv").write_bytes(b"three")


def test_scanner_filters_extensions_and_respects_recursive_flag(tmp_path: Path) -> None:
    recursive_root = tmp_path / "recursive"
    non_recursive_root = tmp_path / "flat"
    _make_media_tree(recursive_root)
    _make_media_tree(non_recursive_root)
    store = LibraryStore(tmp_path / "library.sqlite3")
    recursive = store.add_root(recursive_root, recursive=True)
    flat = store.add_root(non_recursive_root, recursive=False)
    scanner = LocalFolderScanner(store)

    recursive_report = scanner.scan_root(recursive)
    flat_report = scanner.scan_root(flat)

    assert recursive_report.discovered == 3
    assert flat_report.discovered == 2
    assert len(store.list_items(root_id=recursive.id, limit=10)) == 3
    assert len(store.list_items(root_id=flat.id, limit=10)) == 2


def test_scanner_reconciles_unchanged_changed_and_missing_files(tmp_path: Path) -> None:
    media = tmp_path / "media"
    _make_media_tree(media)
    store = LibraryStore(tmp_path / "library.sqlite3")
    root = store.add_root(media)
    scanner = LocalFolderScanner(store)

    first = scanner.scan_root(root)
    second = scanner.scan_root(root)
    assert first.discovered == 3
    assert second.unchanged == 3

    one = media / "one.mp4"
    one.write_bytes(b"one-changed")
    stat = one.stat()
    os.utime(one, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    changed = scanner.scan_root(root)
    assert changed.changed == 1
    changed_item = store.get_item_by_path(one)
    assert changed_item is not None
    assert changed_item.status is LibraryItemStatus.QUEUED

    two = media / "TWO.MOV"
    two.unlink()
    missing = scanner.scan_root(root)
    assert missing.missing == 1
    missing_item = store.get_item_by_path(two)
    assert missing_item is not None
    assert missing_item.status is LibraryItemStatus.MISSING


def test_missing_completed_file_restores_without_reprocessing_when_same_version_returns(
    tmp_path: Path,
) -> None:
    media = tmp_path / "media"
    media.mkdir()
    movie = media / "movie.mp4"
    movie.write_bytes(b"same-content")
    original_stat = movie.stat()
    store = LibraryStore(tmp_path / "library.sqlite3")
    root = store.add_root(media)
    scanner = LocalFolderScanner(store)

    scanner.scan_root(root)
    claimed = store.claim_next()
    assert claimed is not None
    video_id = uuid4()
    store.complete(claimed.id, video_id)

    movie.unlink()
    scanner.scan_root(root)
    missing = store.get_item_by_path(movie)
    assert missing is not None and missing.status is LibraryItemStatus.MISSING

    movie.write_bytes(b"same-content")
    os.utime(movie, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    restored_report = scanner.scan_root(root)

    restored = store.get_item_by_path(movie)
    assert restored is not None
    assert restored.status is LibraryItemStatus.COMPLETED
    assert restored.video_id == video_id
    assert restored.processed_fingerprint == restored.fingerprint
    assert restored_report.changed == 0


def test_scan_all_combines_enabled_roots(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "a.mp4").write_bytes(b"a")
    (second / "b.webm").write_bytes(b"b")
    store = LibraryStore(tmp_path / "library.sqlite3")
    store.add_root(first)
    store.add_root(second)

    report = LocalFolderScanner(store).scan_all()

    assert report.discovered == 2


def test_scanner_skips_symlinked_video(tmp_path: Path) -> None:
    media = tmp_path / "media"
    outside = tmp_path / "outside"
    media.mkdir()
    outside.mkdir()
    target = outside / "outside.mp4"
    target.write_bytes(b"outside")
    link = media / "escape.mp4"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks are not supported in this environment")

    store = LibraryStore(tmp_path / "library.sqlite3")
    root = store.add_root(media)
    report = LocalFolderScanner(store).scan_root(root)

    assert report.discovered == 0
    assert store.list_items(root_id=root.id, limit=10) == []

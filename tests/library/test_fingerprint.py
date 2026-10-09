from pathlib import Path

from clipatlas.library.fingerprint import canonicalize_path, fast_fingerprint


def test_canonicalize_path_returns_absolute_resolved_path(tmp_path: Path) -> None:
    nested = tmp_path / "media" / ".." / "media" / "movie.mp4"
    expected = (tmp_path / "media" / "movie.mp4").resolve()

    assert canonicalize_path(nested) == expected


def test_fast_fingerprint_is_deterministic_and_changes_with_metadata(tmp_path: Path) -> None:
    path = (tmp_path / "Movie.MP4").resolve()
    first = fast_fingerprint(path, 100, 123)

    assert first == fast_fingerprint(path, 100, 123)
    assert first != fast_fingerprint(path, 101, 123)
    assert first != fast_fingerprint(path, 100, 124)
    assert len(first) == 64

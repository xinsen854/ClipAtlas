import hashlib
from pathlib import Path

VENDOR_ROOT = Path(__file__).resolve().parents[2] / "clipatlas/vendor/sentrysearch"
UPSTREAM_REPO = "ssrajadh/sentrysearch"
UPSTREAM_COMMIT = "a89d1282fe52dd98aa71593cda86f8e8b4fbdd3b"
UPSTREAM_LICENSE_GIT_BLOB = "261eeb9e9f8b2b4b0d119366dda99c6fd7d35c64"
UPSTREAM_GIT_BLOBS = {
    "base_embedder.py": "f67461cbc447a3ddcf0deceb792164c4df0e9a57",
    "chunker.py": "0224c69aefa7396fc7b3c89e721ba7223ae335ea",
    "qwen_cloud_embedder.py": "fbc756c20a2a4b83c78fb466bf854ad79a342aef",
    "dlq.py": "3c624685cfe6cc8d41f4c026b6e0ee7c582c854c",
}
FORBIDDEN_UPSTREAM_FILES = {
    "cli.py",
    "store.py",
    "overlay.py",
    "highlights.py",
    "gemini_embedder.py",
    "gemini_reranker.py",
}


def _git_blob_sha(path: Path) -> str:
    # Match the upstream Git blob even when Windows checks text out with CRLF.
    payload = path.read_bytes().replace(b"\r\n", b"\n")
    header = f"blob {len(payload)}\0".encode()
    return hashlib.sha1(header + payload, usedforsecurity=False).hexdigest()


def test_locked_sentrysearch_core_is_vendored_byte_for_byte() -> None:
    assert VENDOR_ROOT.is_dir()
    for filename, expected_sha in UPSTREAM_GIT_BLOBS.items():
        path = VENDOR_ROOT / filename
        assert path.is_file(), filename
        assert _git_blob_sha(path) == expected_sha, filename


def test_vendor_includes_exact_upstream_apache_license() -> None:
    license_path = VENDOR_ROOT / "LICENSE"

    assert license_path.is_file()
    assert _git_blob_sha(license_path) == UPSTREAM_LICENSE_GIT_BLOB


def test_vendor_notice_locks_source_commit_and_license() -> None:
    notice = (VENDOR_ROOT / "NOTICE.md").read_text(encoding="utf-8")

    assert UPSTREAM_REPO in notice
    assert UPSTREAM_COMMIT in notice
    assert "Apache-2.0" in notice
    assert "P0-3" in notice


def test_vendor_scope_excludes_unwanted_sentrysearch_components() -> None:
    present = {path.name for path in VENDOR_ROOT.iterdir() if path.is_file()}

    assert FORBIDDEN_UPSTREAM_FILES.isdisjoint(present)

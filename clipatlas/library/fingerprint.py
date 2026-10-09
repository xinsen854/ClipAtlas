from hashlib import sha256
from pathlib import Path


def canonicalize_path(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def fast_fingerprint(path: Path, size_bytes: int, mtime_ns: int) -> str:
    canonical = canonicalize_path(path)
    payload = f"{canonical}\0{size_bytes}\0{mtime_ns}".encode()
    return sha256(payload).hexdigest()

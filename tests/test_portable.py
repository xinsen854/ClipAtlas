import sys
from pathlib import Path

import pytest

from clipatlas import portable


def test_free_port_skips_occupied_ports(monkeypatch) -> None:
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    occupied = sock.getsockname()[1]
    try:
        chosen = portable._free_port(occupied)
        assert chosen != occupied
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.bind(("127.0.0.1", chosen))
        finally:
            probe.close()
    finally:
        sock.close()


def test_prepare_environment_frozen_layout(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "ClipAtlas"
    bundle = tmp_path / "_internal"
    (bundle / "bin").mkdir(parents=True)
    (bundle / "bin" / "ffmpeg.exe").write_bytes(b"ffmpeg")
    (bundle / "frontend_dist").mkdir(parents=True)
    (bundle / "frontend_dist" / "index.html").write_text("<html></html>")
    (bundle / "data-template" / "config").mkdir(parents=True)
    (bundle / "data-template" / "config" / "settings.json").write_text(
        '{"bailian_api_key": ""}',
        encoding="utf-8",
    )

    monkeypatch.setattr(portable, "_app_root", lambda: root)
    monkeypatch.setattr(portable, "_bundle_root", lambda: bundle)
    monkeypatch.setattr(portable, "_free_port", lambda preferred: preferred)
    monkeypatch.setenv("CLIPATLAS_PORT", "9001")

    got_root, port = portable._prepare_environment()

    assert got_root == root
    assert port == 9001
    # Settings seeded from the template
    seeded = root / "data" / "config" / "settings.json"
    assert seeded.read_text(encoding="utf-8") == '{"bailian_api_key": ""}'
    # Sub directories created
    assert (root / "data" / "library").is_dir()
    assert (root / "data" / "projects").is_dir()
    # ffmpeg directory placed on PATH
    assert portable.os.environ["PATH"].startswith(str(bundle / "bin") + portable.os.pathsep)
    # Frontend dist env points at the bundle copy
    assert portable.os.environ["CLIPATLAS_FRONTEND_DIST"] == str(bundle / "frontend_dist")
    # cwd switched to the app root
    assert Path.cwd() == root


def test_prepare_environment_keeps_existing_settings(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "ClipAtlas"
    bundle = tmp_path / "_internal"
    (bundle / "data-template" / "config").mkdir(parents=True)
    (bundle / "data-template" / "config" / "settings.json").write_text(
        '{"bailian_api_key": "template"}',
        encoding="utf-8",
    )
    config_dir = root / "data" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "settings.json").write_text(
        '{"bailian_api_key": "user-saved"}',
        encoding="utf-8",
    )

    monkeypatch.setattr(portable, "_app_root", lambda: root)
    monkeypatch.setattr(portable, "_bundle_root", lambda: bundle)

    portable._prepare_environment()

    assert (config_dir / "settings.json").read_text(encoding="utf-8") == (
        '{"bailian_api_key": "user-saved"}'
    )

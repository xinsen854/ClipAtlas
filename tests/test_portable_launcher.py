import socket
import sys
from pathlib import Path

from clipatlas import portable


def test_frozen_app_root_is_persistent_and_bundle_root_is_meipass(
    tmp_path: Path, monkeypatch
) -> None:
    app_root = tmp_path / "installed" / "ClipAtlas"
    bundle_root = tmp_path / "onefile-extraction"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(app_root / "ClipAtlas.exe"))
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle_root), raising=False)

    assert portable._app_root() == app_root.resolve()
    assert portable._bundle_root() == bundle_root
    assert portable._app_root() != portable._bundle_root()


def test_prepare_environment_points_frontend_at_bundled_dist(
    tmp_path: Path, monkeypatch
) -> None:
    previous_cwd = Path.cwd()
    app_root = tmp_path / "installed" / "ClipAtlas"
    bundle_root = tmp_path / "bundle"
    app_root.mkdir(parents=True)
    frontend_dist = bundle_root / "frontend_dist"
    frontend_dist.mkdir(parents=True)
    monkeypatch.setattr(portable, "_app_root", lambda: app_root)
    monkeypatch.setattr(portable, "_bundle_root", lambda: bundle_root)
    monkeypatch.setattr(portable, "_free_port", lambda preferred: preferred)
    monkeypatch.delenv("CLIPATLAS_FRONTEND_DIST", raising=False)
    monkeypatch.setenv("CLIPATLAS_PORT", "9876")

    try:
        root, port = portable._prepare_environment()

        assert root == app_root
        assert port == 9876
        assert portable.os.environ["CLIPATLAS_FRONTEND_DIST"] == str(frontend_dist)
        assert not (bundle_root / "data").exists()
    finally:
        portable.os.environ.pop("CLIPATLAS_FRONTEND_DIST", None)
        portable.os.chdir(previous_cwd)


def test_free_port_falls_back_when_preferred_port_is_occupied() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.bind(("127.0.0.1", 0))
        preferred = occupied.getsockname()[1]

        chosen = portable._free_port(preferred)

        assert preferred < chosen < preferred + 20
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", chosen))

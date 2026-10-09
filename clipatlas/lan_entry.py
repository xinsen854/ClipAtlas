"""Minimal frozen entry point that captures import-time failures."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import traceback


def run() -> None:
    config = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ClipAtlasSearch"
    config.mkdir(parents=True, exist_ok=True)
    with open(config / "startup.log", "a", encoding="utf-8", buffering=1) as log:
        sys.stdout = sys.stderr = log
        try:
            from clipatlas.lan_desktop import main
            main()
        except BaseException:
            traceback.print_exc()
            raise


if __name__ == "__main__":
    run()

import argparse
import threading
import time
import webbrowser
from collections.abc import Sequence

import httpx
import uvicorn

HOST = "127.0.0.1"
PORT = 8000
ROOT_URL = f"http://{HOST}:{PORT}"
HEALTH_URL = f"{ROOT_URL}/health"
HEALTH_ATTEMPTS = 50
HEALTH_DELAY_SECONDS = 0.1
HEALTH_TIMEOUT_SECONDS = 1.0


def _open_browser_when_ready() -> None:
    for attempt in range(HEALTH_ATTEMPTS):
        try:
            response = httpx.get(HEALTH_URL, timeout=HEALTH_TIMEOUT_SECONDS)
            if response.status_code == 200:
                frontend_response = httpx.get(ROOT_URL, timeout=HEALTH_TIMEOUT_SECONDS)
                if frontend_response.status_code == 200:
                    webbrowser.open(ROOT_URL)
                return
        except httpx.HTTPError:
            pass

        if attempt + 1 < HEALTH_ATTEMPTS:
            time.sleep(HEALTH_DELAY_SECONDS)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="clipatlas")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)

    if not args.no_browser:
        browser_thread = threading.Thread(target=_open_browser_when_ready, daemon=True)
        browser_thread.start()

    uvicorn.run("clipatlas.main:app", host=HOST, port=PORT)

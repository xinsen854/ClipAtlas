"""Native folder/file pickers for the local web UI.

Browsers cannot return real absolute paths from file inputs, so the portable
app exposes two endpoints that open the OS-native dialog on the backend
machine. tkinter must own its Tk instance from a single thread, therefore all
dialog work happens on a dedicated daemon worker thread fed by a queue.
"""

from __future__ import annotations

import queue
import threading
from typing import Literal

PickerKind = Literal["directory", "file"]

_request_queue: "queue.Queue[tuple[PickerKind, queue.Queue[str | None]]]" = queue.Queue()


def _picker_worker() -> None:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:  # pragma: no cover - no display session
        while True:
            _kind, response = _request_queue.get()
            response.put(None)
        return

    root: tk.Tk | None = None
    while True:
        kind, response = _request_queue.get()
        try:
            if root is None:
                root = tk.Tk()
                root.withdraw()
            root.attributes("-topmost", True)
            root.update()
            if kind == "directory":
                selected = filedialog.askdirectory(parent=root, title="选择文件夹")
            else:
                selected = filedialog.askopenfilename(
                    parent=root,
                    title="选择文件",
                    filetypes=[("可执行文件", "*.exe"), ("所有文件", "*.*")],
                )
            response.put(selected if selected else None)
        except Exception:  # pragma: no cover - dialog failure
            response.put(None)
        finally:
            if root is not None:
                root.attributes("-topmost", False)


_thread = threading.Thread(target=_picker_worker, name="clipatlas-picker", daemon=True)
_thread.start()


def pick(kind: PickerKind) -> str | None:
    """Block until the user picks a path or cancels; returns None on cancel."""
    response: "queue.Queue[str | None]" = queue.Queue(maxsize=1)
    _request_queue.put((kind, response))
    return response.get()

"""Global test isolation for the real local configuration.

``clipatlas.main`` creates the FastAPI app at module import time
(``app = create_app()`` at module level, required by uvicorn), and
``SettingsStore.apply_missing_environment`` injects the persisted API keys
into ``os.environ`` during that call. Without this file, merely importing
``clipatlas.main`` inside any test leaks the real keys from
``data/config/settings.json`` into the test process, breaking tests that
expect embedding providers to be disabled (503) or a specific fake key.

pytest imports conftest before any test module, so pointing
``CLIPATLAS_SETTINGS_FILE`` at an empty settings file here prevents the
injection. Tests that explicitly set their own env still win because
``monkeypatch`` runs later.
"""

import os
from pathlib import Path

_EMPTY_SETTINGS = Path(__file__).parent / "_empty_settings.json"
if not _EMPTY_SETTINGS.exists():
    _EMPTY_SETTINGS.write_text("{}", encoding="utf-8")

os.environ.setdefault("CLIPATLAS_SETTINGS_FILE", str(_EMPTY_SETTINGS))

for _secret_env in (
    "CLIPATLAS_EMBEDDING_API_KEY",
    "CLIPATLAS_BAILIAN_API_KEY",
    "CLIPATLAS_QWEN_API_KEY",
    "CLIPATLAS_SPEECH_API_KEY",
    "DASHSCOPE_API_KEY",
):
    os.environ.pop(_secret_env, None)

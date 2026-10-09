import tomllib
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Any, ClassVar

import pytest

ROOT_URL = "http://127.0.0.1:8000"
HEALTH_URL = f"{ROOT_URL}/health"


def _load_cli() -> ModuleType:
    return import_module("clipatlas.cli")


class _FakeThread:
    instances: ClassVar[list["_FakeThread"]] = []

    def __init__(self, *, target: Any, daemon: bool = False) -> None:
        self.target = target
        self.daemon = daemon
        self.started = False
        self.__class__.instances.append(self)

    def start(self) -> None:
        self.started = True


def test_default_cli_starts_browser_helper_then_runs_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    cli = _load_cli()
    _FakeThread.instances.clear()
    run_calls: list[tuple[str, str, int]] = []

    monkeypatch.setattr(cli.threading, "Thread", _FakeThread)
    monkeypatch.setattr(
        cli.uvicorn,
        "run",
        lambda app, *, host, port: run_calls.append((app, host, port)),
    )

    cli.main([])

    assert run_calls == [("clipatlas.main:app", "127.0.0.1", 8000)]
    assert len(_FakeThread.instances) == 1
    assert _FakeThread.instances[0].daemon is True
    assert _FakeThread.instances[0].started is True


def test_no_browser_skips_helper_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    cli = _load_cli()
    run_calls: list[tuple[str, str, int]] = []

    def fail_thread(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("--no-browser must not create a browser helper thread")

    monkeypatch.setattr(cli.threading, "Thread", fail_thread)
    monkeypatch.setattr(
        cli.uvicorn,
        "run",
        lambda app, *, host, port: run_calls.append((app, host, port)),
    )

    cli.main(["--no-browser"])

    assert run_calls == [("clipatlas.main:app", "127.0.0.1", 8000)]


def test_browser_helper_opens_root_once_after_health_and_frontend_are_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli = _load_cli()
    _FakeThread.instances.clear()
    health_statuses = iter([503, 200])
    calls: list[str] = []
    opened: list[str] = []

    class Response:
        def __init__(self, status_code: int) -> None:
            self.status_code = status_code

    def fake_get(url: str, *, timeout: float) -> Response:
        calls.append(url)
        assert timeout > 0
        if url == HEALTH_URL:
            return Response(next(health_statuses))
        assert url == ROOT_URL
        return Response(200)

    monkeypatch.setattr(cli.threading, "Thread", _FakeThread)
    monkeypatch.setattr(cli.uvicorn, "run", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli.httpx, "get", fake_get)
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: opened.append(url) or True)
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)

    cli.main([])
    _FakeThread.instances[0].target()

    assert calls == [HEALTH_URL, HEALTH_URL, ROOT_URL]
    assert opened == [ROOT_URL]


def test_browser_helper_does_not_open_missing_frontend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli = _load_cli()
    _FakeThread.instances.clear()
    calls: list[str] = []
    opened: list[str] = []

    class Response:
        def __init__(self, status_code: int) -> None:
            self.status_code = status_code

    def fake_get(url: str, *, timeout: float) -> Response:
        calls.append(url)
        assert timeout > 0
        if url == HEALTH_URL:
            return Response(200)
        assert url == ROOT_URL
        return Response(404)

    monkeypatch.setattr(cli.threading, "Thread", _FakeThread)
    monkeypatch.setattr(cli.uvicorn, "run", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli.httpx, "get", fake_get)
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: opened.append(url) or True)

    cli.main([])
    _FakeThread.instances[0].target()

    assert calls == [HEALTH_URL, ROOT_URL]
    assert opened == []


def test_browser_helper_stops_after_bounded_failed_health_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli = _load_cli()
    _FakeThread.instances.clear()
    health_calls = 0
    opened: list[str] = []

    class Response:
        status_code = 503

    def fake_get(url: str, *, timeout: float) -> Response:
        nonlocal health_calls
        assert url == HEALTH_URL
        assert timeout > 0
        health_calls += 1
        if health_calls > 100:
            pytest.fail("health polling must stop after a bounded number of attempts")
        return Response()

    monkeypatch.setattr(cli.threading, "Thread", _FakeThread)
    monkeypatch.setattr(cli.uvicorn, "run", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli.httpx, "get", fake_get)
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: opened.append(url) or True)
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)

    cli.main([])
    _FakeThread.instances[0].target()

    assert 1 <= health_calls <= 100
    assert opened == []


def test_project_registers_clipatlas_console_script() -> None:
    project = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert project["project"]["scripts"]["clipatlas"] == "clipatlas.cli:main"

import json
from io import BytesIO
from pathlib import Path

import pytest

from clipatlas.hypit.service import (
    HypitConfigUpdate,
    HypitConfigurationError,
    HypitService,
)


def update_for(tmp_path: Path, **overrides: object) -> HypitConfigUpdate:
    values: dict[str, object] = {
        "distribution_root": str(tmp_path / "distribution"),
        "workspace": str(tmp_path / "workspace"),
        "run_file": str(tmp_path / "workspace" / "build.svrun"),
        "endpoint": "video.custom",
        "provider_package": "@example/hypit-provider-video",
        "base_url": "https://video.example.test/v1",
        "base_url_field": "baseUrl",
        "credential_field": "apiKey",
        "provider_config": {"model": "video-1", "pollIntervalMs": 5000},
    }
    values.update(overrides)
    return HypitConfigUpdate.model_validate(values)


def test_custom_provider_writes_independent_runtime_without_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = HypitService(tmp_path / "data" / "hypit" / "config.json")
    auth_calls: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        service,
        "_run_auth",
        lambda _config, _runtime, *, action, secret=None: auth_calls.append((action, secret)),
    )

    saved = service.update(update_for(tmp_path, api_key="private-key"))

    runtime_path = tmp_path / "workspace" / ".hypit" / "clipatlas.runtime.json"
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    endpoint = runtime["endpoints"]["video.custom"]
    assert endpoint == {
        "use": "@example/hypit-provider-video",
        "config": {
            "model": "video-1",
            "pollIntervalMs": 5000,
            "baseUrl": "https://video.example.test/v1",
            "apiKey": {"store": "os", "key": "clipatlas.video.custom"},
        },
    }
    assert runtime["endpoints"]["media.local"]["use"] == "@hypit/provider-media-local"
    assert runtime["endpoints"]["hyperframes.local"]["use"] == "@hypit/provider-hyperframes-local"
    assert runtime["credentials"]["os"]["config"]["service"] == "clipatlas-hypit"
    assert "private-key" not in runtime_path.read_text(encoding="utf-8")
    assert "private-key" not in service._config_path.read_text(encoding="utf-8")
    assert saved.api_key_configured is True
    assert auth_calls == [("login", "private-key")]


def test_wavespeed_provider_is_bundled_into_the_selected_distribution(tmp_path: Path) -> None:
    service = HypitService(tmp_path / "data" / "hypit" / "config.json")

    service.update(update_for(
        tmp_path,
        endpoint="wavespeed.default",
        provider_package="@hypit/provider-wavespeed",
        base_url="https://api.wavespeed.ai/api/v3",
        provider_config={"selectedModel": "seedance-2.5", "pollIntervalMs": 5000},
    ))

    package = tmp_path / "distribution" / "packages" / "provider-wavespeed"
    assert (package / "package.json").is_file()
    assert (package / "src" / "activation.js").is_file()
    runtime = json.loads(
        (tmp_path / "workspace" / ".hypit" / "clipatlas.runtime.json").read_text(encoding="utf-8")
    )
    endpoint = runtime["endpoints"]["wavespeed.default"]
    assert endpoint["use"] == "@hypit/provider-wavespeed"
    assert endpoint["config"]["selectedModel"] == "seedance-2.5"


def test_run_file_must_stay_inside_hypit_workspace(tmp_path: Path) -> None:
    service = HypitService(tmp_path / "config.json")

    with pytest.raises(HypitConfigurationError, match="inside its workspace"):
        service.update(update_for(tmp_path, run_file=str(tmp_path / "outside" / "build.svrun")))


def test_studio_command_uses_only_hypit_workspace_and_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = HypitService(tmp_path / "config.json")
    config = service.config().model_copy(
        update={
            "distribution_root": str(tmp_path / "distribution"),
            "workspace": str(tmp_path / "workspace"),
            "run_file": str(tmp_path / "workspace" / "build.svrun"),
        }
    )
    monkeypatch.setattr("clipatlas.hypit.service.shutil.which", lambda _name: "C:/node/node.exe")

    command = service._studio_command(config, tmp_path / "runtime.json", 5180)

    assert command[:3] == [
        "C:/node/node.exe",
        str((tmp_path / "distribution" / "bin" / "hypit.mjs").resolve()),
        "studio",
    ]
    assert command[command.index("--workspace") + 1] == str((tmp_path / "workspace").resolve())
    assert command[command.index("--runtime") + 1] == str(tmp_path / "runtime.json")
    assert command[command.index("--port") + 1] == "5180"


def test_reference_videos_stay_inside_the_independent_workspace(tmp_path: Path) -> None:
    service = HypitService(tmp_path / "data" / "hypit" / "config.json")

    saved = service.import_reference("example.mp4", BytesIO(b"video"), max_bytes=100)

    path = tmp_path / "data" / "hypit" / "workspace" / "assets" / "references" / "example.mp4"
    assert path.read_bytes() == b"video"
    assert saved.name == "example.mp4"
    assert [item.name for item in service.references()] == ["example.mp4"]

    with pytest.raises(HypitConfigurationError, match="supported video file name"):
        service.import_reference("../outside.mp4", BytesIO(b"video"), max_bytes=100)

    service.delete_reference("example.mp4")
    assert not path.exists()


def test_build_and_export_commands_use_only_hypit_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = HypitService(tmp_path / "config.json")
    config = service.config()
    Path(config.run_file).parent.mkdir(parents=True, exist_ok=True)
    Path(config.run_file).write_text("<svrun/>", encoding="utf-8")
    commands: list[list[str]] = []

    def run_cli(_config, arguments, **_kwargs):
        commands.append(arguments)
        if arguments[0] == "get":
            destination = Path(arguments[arguments.index("--to") + 1])
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"result")
        return {"format": "hypit.test@1", "build": {"id": "build-1"}}

    monkeypatch.setattr(service, "_validate_paths", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(service, "_write_runtime", lambda _config: tmp_path / "runtime.json")
    monkeypatch.setattr(service, "_run_cli_json", run_cli)

    service.submit_build("Example")
    exported = service.export_output("build-1", "final.video")

    assert commands[0][0] == "build"
    assert commands[0][commands[0].index("--workspace") + 1] == str(Path(config.workspace).resolve())
    assert commands[0][commands[0].index("--package-root") + 1] == str(Path(config.workspace).resolve())
    assert commands[1][:4] == ["get", "build-1", "--output", "final.video"]
    assert exported.read_bytes() == b"result"

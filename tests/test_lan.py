from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from clipatlas.lan import create_gateway
from clipatlas.lan_files import LocalFiles, fingerprint, source_path
from clipatlas.lan_library import validate_data_root


def test_local_files_match_renamed_copy_by_content(tmp_path: Path) -> None:
    host = tmp_path / "host"
    client = tmp_path / "client"
    host.mkdir()
    client.mkdir()
    original = host / "泰钜700.mp4"
    copy = client / "同事重命名.mp4"
    content = (b"video-content-" * 100_000) + b"end"
    original.write_bytes(content)
    copy.write_bytes(content)

    files = LocalFiles()
    assert files.scan(str(client))["count"] == 1
    result = files.match({
        "filename": original.name,
        "size": original.stat().st_size,
        "fingerprint": fingerprint(original),
    })
    assert result["status"] == "matched"
    assert result["candidates"][0]["name"] == "同事重命名.mp4"
    assert result["candidates"][0]["verified"] is True


def test_source_path_decodes_chinese_file_uri() -> None:
    path = source_path("file:///D:/BaiduNetdiskDownload/%E6%B3%B0%E9%92%9C700.mp4")
    assert path.name == "泰钜700.mp4"


def test_client_rejects_non_local_host_header() -> None:
    with TestClient(create_gateway(), base_url="http://127.0.0.1") as client:
        assert client.get("/lan/folder").status_code == 200
        assert client.get("/lan/folder", headers={"host": "attacker.example"}).status_code == 403


def test_standalone_data_root_validation(tmp_path: Path) -> None:
    (tmp_path / "projects").mkdir()
    (tmp_path / "library").mkdir()
    (tmp_path / "projects" / "projects.sqlite3").touch()
    (tmp_path / "library" / "library.sqlite3").touch()
    assert validate_data_root(tmp_path) == tmp_path.resolve()


def test_client_connects_and_matches_local_copy(tmp_path: Path) -> None:
    original = tmp_path / "host-video.mp4"
    local = tmp_path / "renamed-local.mp4"
    original.write_bytes(b"matching-video-content" * 100_000)
    local.write_bytes(original.read_bytes())
    video_id = "11111111-1111-1111-1111-111111111111"

    def remote(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/lan/info":
            return httpx.Response(200, json={
                "service": "clipatlas-lan-search", "name": "LIBRARY-PC",
                "host": True, "online": True,
            })
        if request.url.path == f"/lan/match/{video_id}":
            return httpx.Response(200, json={
                "filename": original.name,
                "size": original.stat().st_size,
                "fingerprint": fingerprint(original),
            })
        return httpx.Response(404)

    app = create_gateway(transport=httpx.MockTransport(remote))
    with TestClient(app, base_url="http://127.0.0.1") as client:
        connected = client.post("/lan/connect", json={"address": "localhost"})
        assert connected.status_code == 200
        key = connected.json()["prefix"].split("/")[2]
        assert client.post("/lan/folder", json={"path": str(tmp_path)}).status_code == 200
        matched = client.post("/lan/local-match", json={
            "connection": key, "video_id": video_id,
        })
        assert matched.status_code == 200
        assert matched.json()["candidates"][0]["verified"] is True

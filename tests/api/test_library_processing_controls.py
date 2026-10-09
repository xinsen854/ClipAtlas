from pathlib import Path

from fastapi.testclient import TestClient

from clipatlas.main import create_app


class ControllableSupervisor:
    def __init__(self, *, available: bool = True) -> None:
        self.processing_available = available
        self._paused = not available

    @property
    def paused(self) -> bool:
        return self._paused or not self.processing_available

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> bool:
        if not self.processing_available:
            return False
        self._paused = False
        return True


def _client(tmp_path: Path, supervisor: ControllableSupervisor) -> TestClient:
    app = create_app()
    app.state.library_supervisor = supervisor
    return TestClient(app)


def test_processing_status_pause_and_resume_are_explicit_api_actions(tmp_path: Path) -> None:
    supervisor = ControllableSupervisor()
    client = _client(tmp_path, supervisor)

    initial = client.get("/api/v1/library/processing")
    paused = client.post("/api/v1/library/processing/pause")
    resumed = client.post("/api/v1/library/processing/resume")

    assert initial.status_code == 200
    assert initial.json() == {"available": True, "paused": False}
    assert paused.status_code == 200
    assert paused.json() == {"available": True, "paused": True}
    assert resumed.status_code == 200
    assert resumed.json() == {"available": True, "paused": False}


def test_processing_resume_rejects_missing_video_understanding_provider(tmp_path: Path) -> None:
    supervisor = ControllableSupervisor(available=False)
    client = _client(tmp_path, supervisor)

    status = client.get("/api/v1/library/processing")
    resumed = client.post("/api/v1/library/processing/resume")

    assert status.status_code == 200
    assert status.json() == {"available": False, "paused": True}
    assert resumed.status_code == 409
    assert resumed.json()["detail"] == "video understanding provider is not configured"

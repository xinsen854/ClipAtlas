from types import SimpleNamespace
from urllib.parse import quote
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from clipatlas.api.routes.finecut import router as finecut_router
from clipatlas.library.models import LibraryItem, LibraryItemStatus


class _LibraryStore:
    def __init__(self, items: list[LibraryItem]) -> None:
        self.items = items

    def list_items(self, *, limit: int = 100, offset: int = 0, **_: object) -> list[LibraryItem]:
        return self.items[offset : offset + limit]


def test_local_path_identity_reuses_existing_library_resource(tmp_path) -> None:
    project_id = uuid4()
    plan_id = uuid4()
    media_path = (tmp_path / "library-resource.mp4").resolve()
    media_path.touch()
    video_id = uuid4()
    item = LibraryItem(
        root_id=uuid4(),
        source_path=str(media_path),
        size_bytes=1,
        mtime_ns=1,
        fingerprint="editing-draft-resource",
        status=LibraryItemStatus.COMPLETED,
        video_id=video_id,
    )
    plan = SimpleNamespace(id=plan_id, project_id=project_id, clips=[])
    app = FastAPI()
    app.include_router(finecut_router)
    app.state.rough_cut_store = SimpleNamespace(get_plan=lambda value: plan if value == plan_id else None)
    app.state.library_store = _LibraryStore([item])
    client = TestClient(app)

    encoded_source = quote(str(media_path), safe="")
    response = client.get(f"/api/v1/finecut/plans/{plan_id}/media-resolution/{encoded_source}")

    assert response.status_code == 200
    assert response.json() == {"media_id": str(video_id), "source_uri": str(media_path)}

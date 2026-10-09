from fastapi import FastAPI
from fastapi.testclient import TestClient

from clipatlas.api.routes.search import router


def test_deep_pass_is_not_exposed_as_a_public_search_endpoint() -> None:
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    response = client.get(
        "/api/v1/search/deep",
        params={"q": "越野测试"},
    )

    assert response.status_code == 404

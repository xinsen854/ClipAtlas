from fastapi.testclient import TestClient

from clipatlas.main import create_app


def test_health_endpoint():
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "clipatlas", "version": "1.1.4"}

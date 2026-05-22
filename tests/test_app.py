from fastapi.testclient import TestClient

from app import app


def test_root_returns_ok():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200

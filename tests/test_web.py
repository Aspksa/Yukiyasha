from fastapi.testclient import TestClient

from yukiyasha.web.app import app


def test_health_endpoint() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "Yukiyasha",
        "version": "0.1.0",
    }


def test_runtime_endpoint() -> None:
    with TestClient(app) as client:
        response = client.get("/api/runtime")

    payload = response.json()
    assert response.status_code == 200
    assert payload["state"] == "ready"
    assert payload["version"] == "0.1.0"


def test_web_root() -> None:
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "Yukiyasha" in response.text

from fastapi.testclient import TestClient

from yukiyasha.web.app import app


def test_health_endpoint() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "Yukiyasha",
        "version": "0.2.0",
    }


def test_runtime_endpoint() -> None:
    with TestClient(app) as client:
        response = client.get("/api/runtime")

    payload = response.json()
    assert response.status_code == 200
    assert payload["state"] == "ready"
    assert payload["version"] == "0.2.0"


def test_modules_endpoint_exposes_disk() -> None:
    with TestClient(app) as client:
        response = client.get("/api/modules")

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["manifest"]["module_id"] == "disk"
    assert payload[0]["state"] == "ready"


def test_disk_api_roundtrip() -> None:
    path = "tests/api-roundtrip.txt"

    with TestClient(app) as client:
        write = client.put(
            "/api/disk/file",
            json={"path": path, "content": "Yukiyasha Disk", "overwrite": True},
        )
        read = client.get("/api/disk/file", params={"path": path})
        listing = client.get("/api/disk", params={"path": "tests"})
        delete = client.delete("/api/disk/file", params={"path": path})

    assert write.status_code == 200
    assert read.json()["content"] == "Yukiyasha Disk"
    assert any(item["name"] == "api-roundtrip.txt" for item in listing.json()["entries"])
    assert delete.status_code == 200


def test_disk_api_blocks_traversal() -> None:
    with TestClient(app) as client:
        response = client.put(
            "/api/disk/file",
            json={"path": "../escape.txt", "content": "blocked"},
        )

    assert response.status_code == 400


def test_web_root() -> None:
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "Yukiyasha" in response.text

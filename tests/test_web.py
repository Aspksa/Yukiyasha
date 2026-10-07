from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from yukiyasha.config import Settings
from yukiyasha.modules.disk import DiskPermissionError
from yukiyasha.version import get_version
from yukiyasha.web.app import MAX_REQUEST_BODY_BYTES, create_app


@pytest.fixture
def client(tmp_path: Path):
    app = create_app(Settings(disk_dir=tmp_path / "disk"))
    with TestClient(app) as test_client:
        yield test_client


def test_health_endpoint(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "Yukiyasha",
        "version": get_version(),
    }


def test_runtime_endpoint(client: TestClient) -> None:
    response = client.get("/api/runtime")

    payload = response.json()
    assert response.status_code == 200
    assert payload["state"] == "ready"
    assert payload["version"] == get_version()
    assert payload["started_at"] is not None


def test_modules_endpoint_exposes_disk(client: TestClient) -> None:
    response = client.get("/api/modules")

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["manifest"]["module_id"] == "disk"
    assert payload[0]["state"] == "ready"


def test_disk_api_roundtrip(client: TestClient) -> None:
    path = "tests/api-roundtrip.txt"

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


def test_disk_list_missing_directory_is_404(client: TestClient) -> None:
    response = client.get("/api/disk", params={"path": "missing"})

    assert response.status_code == 404
    assert response.json()["detail"] == "Directory not found"


def test_disk_read_missing_file_is_404(client: TestClient) -> None:
    response = client.get("/api/disk/file", params={"path": "missing.txt"})

    assert response.status_code == 404


def test_disk_read_directory_is_400(client: TestClient) -> None:
    response = client.get("/api/disk/file", params={"path": "projects"})

    assert response.status_code == 400
    assert response.json()["detail"] == "Path is a directory"


def test_disk_parent_file_conflict_is_clear_409(client: TestClient) -> None:
    client.put("/api/disk/file", json={"path": "a.txt", "content": "file"})

    response = client.put(
        "/api/disk/file",
        json={"path": "a.txt/b.txt", "content": "blocked"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Parent path is not a directory"


def test_disk_overwrite_false_is_409(client: TestClient) -> None:
    client.put("/api/disk/file", json={"path": "a.txt", "content": "first"})

    response = client.put(
        "/api/disk/file",
        json={"path": "a.txt", "content": "second", "overwrite": False},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "File already exists"


def test_disk_surrogate_content_is_clear_400(client: TestClient) -> None:
    response = client.put(
        "/api/disk/file",
        content='{"path":"bad.txt","content":"\\ud800"}',
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Content must be valid UTF-8 text"


def test_disk_content_limit_is_413(client: TestClient) -> None:
    response = client.put(
        "/api/disk/file",
        json={"path": "big.txt", "content": "x" * (1_048_576 + 1)},
    )

    assert response.status_code == 413


def test_http_body_limit_rejects_before_json_parsing(client: TestClient) -> None:
    response = client.put(
        "/api/disk/file",
        content=b"x" * (MAX_REQUEST_BODY_BYTES + 1),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "Request body too large"


def test_delete_non_empty_directory_is_409(client: TestClient) -> None:
    client.put("/api/disk/file", json={"path": "folder/file.txt", "content": "data"})

    response = client.delete("/api/disk/file", params={"path": "folder"})

    assert response.status_code == 409
    assert response.json()["detail"] == "Directory is not empty"


def test_permission_error_is_403(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = client.app.state.runtime

    def deny(_: str) -> None:
        raise DiskPermissionError("Filesystem permission denied")

    monkeypatch.setattr(runtime.disk, "delete", deny)

    response = client.delete("/api/disk/file", params={"path": "blocked.txt"})

    assert response.status_code == 403


def test_disk_api_blocks_traversal(client: TestClient) -> None:
    response = client.put(
        "/api/disk/file",
        json={"path": "../escape.txt", "content": "blocked"},
    )

    assert response.status_code == 400


def test_disk_api_rejects_untrusted_origin(client: TestClient) -> None:
    response = client.get(
        "/api/disk",
        headers={"origin": "https://attacker.example"},
    )

    assert response.status_code == 403


def test_api_rejects_untrusted_host(client: TestClient) -> None:
    response = client.get("/api/health", headers={"host": "attacker.example"})

    assert response.status_code == 400


def test_web_root(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "Yukiyasha" in response.text

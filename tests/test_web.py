import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from yukiyasha.config import Settings
from yukiyasha.modules.disk import DiskPermissionError
from yukiyasha.version import get_version
from yukiyasha.web.app import MAX_REQUEST_BODY_BYTES, create_app
from yukiyasha.web.middleware import RequestBodyLimitMiddleware


@pytest.fixture
def client(tmp_path: Path):
    app = create_app(Settings(disk_dir=tmp_path / "disk"))
    with TestClient(app, base_url="http://127.0.0.1:8000") as test_client:
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



def test_http_body_limit_rejects_chunked_stream_without_content_length() -> None:
    sent: list[dict[str, object]] = []
    chunks = iter(
        [
            {"type": "http.request", "body": b"abc", "more_body": True},
            {"type": "http.request", "body": b"def", "more_body": False},
        ]
    )

    async def downstream(scope, receive, send) -> None:
        raise AssertionError("Oversized body must not reach downstream app")

    async def receive() -> dict[str, object]:
        return next(chunks)

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    async def run() -> None:
        middleware = RequestBodyLimitMiddleware(downstream, max_bytes=5)
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "PUT",
            "scheme": "http",
            "path": "/api/disk/file",
            "raw_path": b"/api/disk/file",
            "query_string": b"",
            "headers": [(b"content-type", b"application/json")],
            "client": ("127.0.0.1", 12345),
            "server": ("127.0.0.1", 8000),
        }
        await middleware(scope, receive, send)

    asyncio.run(run())

    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 413
    assert sent[1]["type"] == "http.response.body"
    assert b"Request body too large" in sent[1]["body"]

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


@pytest.mark.parametrize(
    ("method", "url", "kwargs"),
    [
        ("get", "/api/disk", {"params": {"path": "a\x00b"}}),
        ("get", "/api/disk/file", {"params": {"path": "a\x00b"}}),
        ("put", "/api/disk/file", {"json": {"path": "a\x00b", "content": "x"}}),
        ("delete", "/api/disk/file", {"params": {"path": "a\x00b"}}),
    ],
)
def test_disk_api_nul_path_is_400(
    client: TestClient, method: str, url: str, kwargs: dict[str, object]
) -> None:
    response = getattr(client, method)(url, **kwargs)

    assert response.status_code == 400
    assert "NUL" in response.json()["detail"]


def test_workspace_ui_markup_contract(client: TestClient) -> None:
    """The browser UI relies on these element ids; keep markup and script in sync."""
    html = client.get("/").text
    script = client.get("/static/app.js").text

    assert client.get("/static/style.css").status_code == 200
    assert client.get("/static/util.js").status_code == 200
    assert 'src="/static/util.js"' in html
    for element_id in (
        "entries",
        "editor-text",
        "btn-save",
        "btn-new",
        "crumbs",
        "modules",
        "dlg-new",
        "dlg-confirm",
    ):
        assert f'id="{element_id}"' in html
        assert f'"#{element_id}"' in script or f"#{element_id}" in script


def test_workspace_ui_uses_only_existing_api_routes(client: TestClient) -> None:
    script = client.get("/static/app.js").text
    routes = {route.path for route in client.app.routes}

    for endpoint in ("/api/disk", "/api/disk/file", "/api/runtime", "/api/modules"):
        assert endpoint in routes
        assert f'"{endpoint}"' in script


@pytest.mark.parametrize(
    "origin",
    [
        "http://evil.example",
        "null",
        "http://127.0.0.1.evil.example",
        "http://127.0.0.1:9999",  # another local app on a different port
        "https://127.0.0.1:8000",  # different scheme
    ],
)
def test_disk_api_rejects_foreign_origin(client: TestClient, origin: str) -> None:
    response = client.put(
        "/api/disk/file",
        json={"path": "x.txt", "content": "x"},
        headers={"Origin": origin},
    )

    assert response.status_code == 403
    assert client.get("/api/disk", params={"path": ""}).json()["entries"][0]["name"] == "projects"


def test_disk_api_accepts_same_origin(client: TestClient) -> None:
    response = client.put(
        "/api/disk/file",
        json={"path": "x.txt", "content": "x"},
        headers={"Origin": "http://127.0.0.1:8000"},
    )

    assert response.status_code == 200


def test_unknown_host_header_is_rejected(client: TestClient) -> None:
    assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 400
    assert client.get("/api/health", headers={"Host": "testserver"}).status_code == 400


def test_security_headers_and_cache_rules(client: TestClient) -> None:
    page = client.get("/")
    api = client.get("/api/runtime")
    docs = client.get("/docs")

    assert page.headers["x-content-type-options"] == "nosniff"
    assert page.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    assert "script-src 'self'" in page.headers["content-security-policy"]
    assert page.headers["cache-control"] == "no-cache"
    assert api.headers["cache-control"] == "no-store"
    assert "content-security-policy" not in docs.headers  # Swagger UI needs its CDN assets


def test_ui_has_no_inline_scripts_or_styles(client: TestClient) -> None:
    """The CSP forbids inline code, so the page must not depend on it."""
    html = client.get("/").text

    assert " style=" not in html
    assert "<style" not in html
    assert "onclick=" not in html
    assert "<script>" not in html


def test_disk_not_ready_maps_to_503() -> None:
    from yukiyasha.modules.disk import DiskNotReadyError
    from yukiyasha.web.app import disk_http_error

    error = disk_http_error(DiskNotReadyError("Yukiyasha Disk is not ready: stopped"))

    assert error.status_code == 503


def test_reserved_temp_name_is_rejected_over_http(client: TestClient) -> None:
    response = client.put(
        "/api/disk/file", json={"path": ".yukiyasha-ab12cd34", "content": "x"}
    )

    assert response.status_code == 400

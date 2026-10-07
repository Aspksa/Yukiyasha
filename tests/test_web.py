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
        "view-module",
        "module-groups",
        "dlg-new",
        "dlg-confirm",
    ):
        assert f'id="{element_id}"' in html
        assert f'"#{element_id}"' in script or f"#{element_id}" in script


def test_workspace_ui_uses_only_existing_api_routes(client: TestClient) -> None:
    script = client.get("/static/app.js").text
    routes = {route.path for route in client.app.routes}

    endpoints = (
        "/api/disk",
        "/api/disk/file",
        "/api/runtime",
        "/api/modules",
        "/api/primavtodor/sections",
    )
    for endpoint in endpoints:
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
    names = [e["name"] for e in client.get("/api/disk", params={"path": ""}).json()["entries"]]
    assert "x.txt" not in names  # the rejected request wrote nothing


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


def test_primavtodor_module_is_listed_and_its_folder_is_in_the_work_section(
    client: TestClient,
) -> None:
    modules = {item["manifest"]["module_id"]: item for item in client.get("/api/modules").json()}

    assert modules["primavtodor"]["manifest"]["name"] == "Примавтодор"
    assert modules["primavtodor"]["state"] == "ready"

    entries = client.get("/api/disk", params={"path": "projects/work"}).json()["entries"]
    assert {"name": "Примавтодор", "path": "projects/work/Примавтодор", "type": "directory",
            "size": 0} in entries


def test_primavtodor_sections_endpoint_counts_documents_on_the_disk(client: TestClient) -> None:
    response = client.get("/api/primavtodor/sections")

    assert response.status_code == 200
    sections = response.json()
    assert [item["title"] for item in sections] == [
        "Путевые листы",
        "Горюче-смазочные материалы",
        "Сотрудники",
        "Гараж",
        "Табель",
        "Договора",
        "Счёт-оферта",
        "Служебные записки",
        "Приказы",
        "Распоряжения",
    ]
    assert all(item["count"] == 0 for item in sections)

    # A file written through the generic disk API is visible in the section's count.
    path = "projects/work/Примавтодор/Приказы/приказ-1.md"
    assert client.put("/api/disk/file", json={"path": path, "content": "x"}).status_code == 200
    orders = next(item for item in client.get("/api/primavtodor/sections").json()
                  if item["id"] == "orders")
    assert orders["count"] == 1
    assert orders["path"] == "projects/work/Примавтодор/Приказы"


def test_primavtodor_sections_endpoint_is_503_when_the_module_is_not_ready(
    client: TestClient,
) -> None:
    client.app.state.runtime.primavtodor.stop()

    response = client.get("/api/primavtodor/sections")

    assert response.status_code == 503


def test_every_primavtodor_section_has_an_icon_and_a_colour(client: TestClient) -> None:
    """The UI derives icon `i-sec-<id>` and colour `[data-sec="<id>"]` from the section id."""
    from yukiyasha.modules.primavtodor import SECTIONS

    html = client.get("/").text
    css = client.get("/static/style.css").text
    hues = []

    for section in SECTIONS:
        assert f'id="i-sec-{section.id}"' in html, f"missing icon for {section.id}"
        rule = f'[data-sec="{section.id}"] {{ --h: '
        assert rule in css, f"missing colour for {section.id}"
        hues.append(int(css.split(rule)[1].split(";")[0]))

    assert len(set(hues)) == len(hues), "section hues must be distinct"


# ----- Примавтодор records API -----

BASE = "/api/primavtodor"


def _post(client: TestClient, kind: str, payload: dict[str, object]):
    return client.post(f"{BASE}/records/{kind}", json=payload)


def _chain(client: TestClient) -> dict[str, str]:
    """vehicle -> driver (card + car) -> waybill; returns the ids."""
    vehicle = _post(client, "vehicles", {"plate": "А123ВБ125", "model": "КАМАЗ",
                                         "norm_summer": 30, "norm_winter": 36}).json()
    driver = _post(client, "employees", {"full_name": "Иванов И.И.", "is_driver": True,
                                         "fuel_card_number": "7001", "vehicle_id": vehicle["id"],
                                         "personnel_number": "1"}).json()
    waybill = _post(client, "waybills", {"number": "1", "date": "2026-10-05",
                                         "driver_id": driver["id"], "vehicle_id": vehicle["id"],
                                         "odometer_out": 1000}).json()
    return {"vehicle": vehicle["id"], "driver": driver["id"], "waybill": waybill["id"]}


def test_primavtodor_schema_describes_every_kind(client: TestClient) -> None:
    payload = client.get(f"{BASE}/schema").json()

    kinds = {entity["kind"]: entity for entity in payload["entities"]}
    assert set(kinds) == {"employees", "vehicles", "waybills", "fuel"}
    assert kinds["waybills"]["section_id"] == "waybills"
    fields = {f["name"]: f for f in kinds["employees"]["fields"]}
    assert fields["fuel_card_number"]["label"] == "Номер топливной карты"
    assert fields["vehicle_id"]["ref"] == "vehicles"
    assert [c["code"] for c in payload["timesheet_codes"]][:2] == ["Я", "В"]


def test_primavtodor_full_chain_over_http(client: TestClient) -> None:
    ids = _chain(client)

    fuel = _post(client, "fuel", {"waybill_id": ids["waybill"], "date": "2026-10-05",
                                  "liters": 40, "price_per_liter": 60})
    assert fuel.status_code == 201
    assert fuel.json()["values"]["card_number"] == "7001"
    assert fuel.json()["computed"]["amount"] == 2400

    waybill = client.get(f"{BASE}/records/waybills/{ids['waybill']}").json()
    assert waybill["computed"]["fuel_issued"] == 40
    assert waybill["labels"]["driver_id"] == "Иванов И.И."

    listing = client.get(f"{BASE}/records/waybills").json()
    assert [r["id"] for r in listing["records"]] == [ids["waybill"]]

    # The records are real files in the section folders, visible through the disk API too.
    files = client.get("/api/disk", params={"path": "projects/work/Примавтодор/Путевые листы"})
    assert [e["name"] for e in files.json()["entries"]] == [f"{ids['waybill']}.json"]


def test_primavtodor_validation_is_422_with_field_messages(client: TestClient) -> None:
    response = _post(client, "vehicles", {"plate": "", "model": "x", "norm_summer": "abc"})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["message"]
    assert set(detail["fields"]) == {"plate", "norm_summer"}


def test_primavtodor_conflict_not_found_and_unknown_kind(client: TestClient) -> None:
    ids = _chain(client)

    in_use = client.delete(f"{BASE}/records/vehicles/{ids['vehicle']}")
    assert in_use.status_code == 409
    assert in_use.json()["detail"]["references"]

    assert client.get(f"{BASE}/records/vehicles/veh-00000000").status_code == 404
    assert client.get(f"{BASE}/records/nothing").status_code == 404
    assert client.get(f"{BASE}/records/vehicles/..%2F..%2Fx").status_code == 404
    assert client.delete(f"{BASE}/records/waybills/{ids['waybill']}").status_code == 200
    assert client.get(f"{BASE}/records/waybills/{ids['waybill']}").status_code == 404


def test_primavtodor_update_over_http(client: TestClient) -> None:
    ids = _chain(client)
    current = client.get(f"{BASE}/records/vehicles/{ids['vehicle']}").json()["values"]

    response = client.put(
        f"{BASE}/records/vehicles/{ids['vehicle']}", json={**current, "model": "МАЗ"}
    )

    assert response.status_code == 200
    assert response.json()["values"]["model"] == "МАЗ"


def test_primavtodor_timesheet_over_http(client: TestClient) -> None:
    ids = _chain(client)

    sheet = client.get(f"{BASE}/timesheet", params={"month": "2026-10"}).json()
    cells = {c["date"]: c for c in sheet["rows"][0]["cells"]}
    assert cells["2026-10-05"]["code"] == "Я"

    marked = client.put(f"{BASE}/timesheet/mark", json={
        "month": "2026-10", "employee_id": ids["driver"], "date": "2026-10-06", "code": "ОТ"})
    assert marked.status_code == 200
    sheet = client.get(f"{BASE}/timesheet", params={"month": "2026-10"}).json()
    assert {c["date"]: c["code"] for c in sheet["rows"][0]["cells"]}["2026-10-06"] == "ОТ"

    assert client.get(f"{BASE}/timesheet", params={"month": "2026-99"}).status_code == 422
    assert client.get(f"{BASE}/timesheet").status_code == 200  # defaults to the current month


def test_primavtodor_changes_reject_foreign_origins(client: TestClient) -> None:
    evil = {"Origin": "http://evil.example"}

    created = client.post(f"{BASE}/records/vehicles", json={"plate": "A1", "model": "x"},
                          headers=evil)
    marked = client.put(f"{BASE}/timesheet/mark", json={
        "month": "2026-10", "employee_id": "emp-00000000", "date": "2026-10-01"}, headers=evil)

    assert created.status_code == 403 and marked.status_code == 403
    assert client.get(f"{BASE}/records/vehicles").json()["records"] == []
    # reading with a foreign Origin header stays possible (the response is unreadable anyway)
    assert client.get(f"{BASE}/records/vehicles", headers=evil).status_code == 200


def test_primavtodor_records_are_503_when_the_module_is_not_ready(client: TestClient) -> None:
    client.app.state.runtime.primavtodor.stop()

    assert client.get(f"{BASE}/records/vehicles").status_code == 503
    assert client.post(f"{BASE}/records/vehicles", json={}).status_code == 503


def test_every_element_id_used_by_the_scripts_exists_in_the_page(client: TestClient) -> None:
    """Catches markup/script drift: a renamed id would otherwise only fail in the browser."""
    import re

    html = client.get("/").text
    used: dict[str, set[str]] = {
        "app.js": set(re.findall(r'\$\("#([\w-]+)"\)', client.get("/static/app.js").text)),
        "primavtodor.js": set(
            re.findall(r'pvById\("([\w-]+)"\)', client.get("/static/primavtodor.js").text)
        ),
        "ai.js": set(re.findall(r'aiById\("([\w-]+)"\)', client.get("/static/ai.js").text)),
    }

    # Form inputs are generated from the schema as "f-<field>"; they must name a real field.
    field_names = {
        f["name"] for e in client.get(f"{BASE}/schema").json()["entities"] for f in e["fields"]
    }

    for script, ids in used.items():
        assert ids, f"no element ids found in {script}"
        generated = {i for i in ids if i.startswith(("f-", "e-"))}
        assert {i[2:] for i in generated} <= field_names, f"{script}: unknown form field"
        missing = sorted(i for i in ids - generated if f'id="{i}"' not in html)
        assert not missing, f"{script} uses ids that are not in index.html: {missing}"


def test_primavtodor_script_is_served_before_app_js(client: TestClient) -> None:
    html = client.get("/").text

    assert html.index("/static/util.js") < html.index("/static/primavtodor.js")
    assert html.index("/static/primavtodor.js") < html.index("/static/ai.js")
    assert html.index("/static/ai.js") < html.index("/static/app.js")


def test_primavtodor_schema_carries_section_paths(client: TestClient) -> None:
    payload = client.get(f"{BASE}/schema").json()

    waybills = next(e for e in payload["entities"] if e["kind"] == "waybills")
    assert waybills["path"] == "projects/work/Примавтодор/Путевые листы"
    assert payload["timesheet"] == {
        "section_id": "timesheet",
        "title": "Табель",
        "path": "projects/work/Примавтодор/Табель",
    }


# ----- summer / winter switch over HTTP -----

def test_season_switch_changes_every_active_norm_at_once(client: TestClient) -> None:
    ids = _chain(client)  # vehicle: summer 30, winter 36; one open waybill

    assert client.put(f"{BASE}/settings/season", json={"season": "summer"}).status_code == 200
    summer = client.get(f"{BASE}/records/vehicles/{ids['vehicle']}").json()
    assert summer["computed"]["norm_active"] == 30

    response = client.put(f"{BASE}/settings/season", json={"season": "winter"})

    assert response.status_code == 200
    body = response.json()
    assert body["season"] == "winter" and body["season_label"] == "Зима"
    assert body["source"] == "manual" and body["updated_waybills"] == 1
    winter = client.get(f"{BASE}/records/vehicles/{ids['vehicle']}").json()
    assert winter["computed"]["norm_active"] == 36
    assert winter["computed"]["norm_active_season"] == "Зима"
    waybill = client.get(f"{BASE}/records/waybills/{ids['waybill']}").json()
    assert waybill["values"]["season"] == "winter"
    assert client.get(f"{BASE}/settings").json()["season"] == "winter"
    schema = client.get(f"{BASE}/schema").json()
    assert schema["settings"]["season"] == "winter"
    assert [s["value"] for s in schema["seasons"]] == ["summer", "winter"]


def test_season_switch_validation_and_origin(client: TestClient) -> None:
    bad = client.put(f"{BASE}/settings/season", json={"season": "autumn"})
    evil = client.put(f"{BASE}/settings/season", json={"season": "winter"},
                      headers={"Origin": "http://evil.example"})

    assert bad.status_code == 422 and "season" in bad.json()["detail"]["fields"]
    assert evil.status_code == 403
    assert client.get(f"{BASE}/settings").json()["source"] == "calendar"  # nothing was stored


# ----- AI assistant over HTTP -----

AI_SECRET = "sk-web-SECRET-456"


@pytest.fixture
def ai_client(tmp_path: Path):
    from tests.fake_provider import FakeProvider
    from yukiyasha.config import AiSettings

    with FakeProvider(chunks=["Здравствуйте", ", ", "Господин"]) as provider:
        settings = Settings(
            disk_dir=tmp_path / "disk",
            ai=AiSettings(base_url=provider.base_url, model="test-model", api_key=AI_SECRET),
        )
        with TestClient(create_app(settings), base_url="http://127.0.0.1:8000") as test_client:
            test_client.provider = provider
            yield test_client


def _sse_events(response) -> list[dict]:
    import json

    return [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]


def test_ai_status_without_a_key_explains_what_to_do(client: TestClient) -> None:
    status = client.get("/api/ai/status").json()

    assert status["configured"] is False and "не настроен" in status["problem"]
    assert status["persona_path"] == "ai/persona.md"
    response = client.post("/api/ai/chat", json={"message": "привет"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "not_configured"


def test_ai_chat_streams_events_and_saves_the_conversation(ai_client: TestClient) -> None:
    response = ai_client.post("/api/ai/chat", json={"message": "Привет"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-store"
    events = _sse_events(response)
    assert [e["type"] for e in events] == ["meta", "delta", "delta", "delta", "done"]
    chat_id = events[0]["conversation_id"]

    listing = ai_client.get("/api/ai/conversations").json()["conversations"]
    assert [c["id"] for c in listing] == [chat_id] and listing[0]["title"] == "Привет"
    chat = ai_client.get(f"/api/ai/conversations/{chat_id}").json()
    assert chat["messages"][1]["content"] == "Здравствуйте, Господин"

    # a follow-up in the same conversation
    again = _sse_events(
        ai_client.post("/api/ai/chat", json={"message": "ещё", "conversation_id": chat_id})
    )
    assert again[-1]["type"] == "done"
    assert len(ai_client.get(f"/api/ai/conversations/{chat_id}").json()["messages"]) == 4

    # the chat is a real file on the disk
    files = ai_client.get("/api/disk", params={"path": "ai/chats"}).json()["entries"]
    assert [f["name"] for f in files] == [f"{chat_id}.json"]
    assert ai_client.delete(f"/api/ai/conversations/{chat_id}").status_code == 200
    assert ai_client.get(f"/api/ai/conversations/{chat_id}").status_code == 404


def test_ai_key_never_appears_in_any_response(ai_client: TestClient) -> None:
    ai_client.post("/api/ai/chat", json={"message": "Привет"})
    texts = [
        ai_client.get("/api/ai/status").text,
        ai_client.get("/api/modules").text,
        ai_client.get("/api/ai/conversations").text,
        ai_client.get("/api/ai/persona").text,
        ai_client.get("/openapi.json").text,
        ai_client.get("/api/runtime").text,
    ]

    assert all(AI_SECRET not in text for text in texts)
    assert ai_client.provider.requests[0]["auth"] == f"Bearer {AI_SECRET}"  # but it is sent


def test_ai_errors_have_clear_statuses(ai_client: TestClient) -> None:
    assert ai_client.post("/api/ai/chat", json={"message": "   "}).status_code == 422
    assert ai_client.post("/api/ai/chat", json={"message": "x" * 9000}).status_code == 422
    missing = ai_client.post("/api/ai/chat",
                             json={"message": "привет", "conversation_id": "chat-00000000"})
    assert missing.status_code == 404
    assert ai_client.get("/api/ai/conversations/..%2F..%2Fx").status_code == 404
    assert ai_client.post("/api/ai/chat", json={}).status_code == 422  # pydantic: no message

    ai_client.provider.status = 401
    rejected = ai_client.post("/api/ai/chat", json={"message": "привет"})
    assert rejected.status_code == 502
    assert "отклонил ключ" in rejected.json()["detail"]["message"]
    assert AI_SECRET not in rejected.text
    assert ai_client.get("/api/ai/conversations").json()["conversations"] == []


def test_ai_persona_roundtrip_over_http(ai_client: TestClient) -> None:
    assert "Помощник" in ai_client.get("/api/ai/persona").json()["text"]

    assert ai_client.put("/api/ai/persona", json={"text": "Ты — Саюри."}).status_code == 200
    assert ai_client.put("/api/ai/persona", json={"text": "  "}).status_code == 422

    assert ai_client.get("/api/ai/persona").json()["text"].strip() == "Ты — Саюри."
    ai_client.post("/api/ai/chat", json={"message": "Привет"})
    sent = ai_client.provider.requests[-1]["body"]["messages"][0]
    assert sent == {"role": "system", "content": "Ты — Саюри.\n"}


def test_ai_changes_reject_foreign_origins(ai_client: TestClient) -> None:
    evil = {"Origin": "http://evil.example"}

    chat = ai_client.post("/api/ai/chat", json={"message": "привет"}, headers=evil)
    persona = ai_client.put("/api/ai/persona", json={"text": "взлом"}, headers=evil)
    removed = ai_client.delete("/api/ai/conversations/chat-00000000", headers=evil)

    assert chat.status_code == persona.status_code == removed.status_code == 403
    assert not ai_client.provider.requests  # the provider was never called (no cost, no leak)
    assert "взлом" not in ai_client.get("/api/ai/persona").json()["text"]


def test_body_limit_hands_the_connection_back_after_the_body_is_read() -> None:
    """A streaming response waits for ``http.disconnect`` after the request body is consumed.

    The middleware used to answer that wait with an endless stream of empty request messages,
    which starved the event loop and froze every streamed POST response (e.g. the AI chat).
    """
    calls = {"after_body": 0}
    disconnect = {"type": "http.disconnect"}

    async def real_receive() -> dict[str, object]:
        calls["after_body"] += 1
        return disconnect

    queue = [{"type": "http.request", "body": b"{}", "more_body": False}]

    async def receive() -> dict[str, object]:
        return queue.pop(0) if queue else await real_receive()

    async def downstream(scope, receive, send) -> None:
        assert (await receive())["type"] == "http.request"  # the buffered body
        assert (await receive()) == disconnect  # then the *real* receive, not a fake body
        assert (await receive()) == disconnect

    async def send(message: dict[str, object]) -> None:  # pragma: no cover - unused
        raise AssertionError("nothing should be sent")

    scope = {"type": "http", "method": "POST", "path": "/api/ai/chat", "headers": []}

    asyncio.run(RequestBodyLimitMiddleware(downstream, max_bytes=100)(scope, receive, send))

    assert calls["after_body"] == 2


def test_a_streamed_post_response_completes_through_the_middleware(
    tmp_path: Path,
) -> None:
    """End to end: a POST that streams its answer must finish (no event-loop starvation)."""
    from fastapi.responses import StreamingResponse

    app = create_app(Settings(disk_dir=tmp_path / "disk"))

    @app.post("/api/test-stream")
    def stream() -> StreamingResponse:
        return StreamingResponse(iter(["data: 1\n\n", "data: 2\n\n"]),
                                 media_type="text/event-stream")

    with TestClient(app, base_url="http://127.0.0.1:8000") as test_client:
        response = test_client.post("/api/test-stream", json={})

    assert response.text == "data: 1\n\ndata: 2\n\n"

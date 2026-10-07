import json
from pathlib import Path

import pytest

from yukiyasha.modules.ai.tools import AiToolRegistry
from yukiyasha.modules.audit import AuditLog
from yukiyasha.modules.disk import DiskAccess, DiskModule
from yukiyasha.modules.manifest import ModuleManifest
from yukiyasha.modules.permissions import PermissionBroker, PermissionDeniedError
from yukiyasha.modules.primavtodor import PrimavtodorModule, PrimavtodorReadAccess


def manifest(module_id: str, *permissions: str) -> ModuleManifest:
    return ModuleManifest(
        module_id=module_id,
        name=module_id,
        version="test",
        description="test",
        permissions=permissions,
    )


def test_permission_broker_is_default_deny() -> None:
    broker = PermissionBroker()
    broker.register(manifest("reader", "disk.read"))

    assert broker.allowed("reader", "disk.read")
    assert not broker.allowed("reader", "disk.write")
    assert not broker.allowed("unknown", "disk.read")
    assert broker.permissions("reader") == ("disk.read",)

    with pytest.raises(PermissionDeniedError):
        broker.require("reader", "disk.write")
    with pytest.raises(PermissionDeniedError):
        broker.require("unknown", "disk.read")


def test_disk_access_checks_permission_and_path_scope(tmp_path: Path) -> None:
    disk = DiskModule(tmp_path / "disk")
    disk.start()
    disk.make_dir("allowed")
    disk.write_text("allowed/read.txt", "ok")
    disk.write_text("outside.txt", "secret")

    broker = PermissionBroker()
    broker.register(manifest("reader", "disk.read"))
    access = DiskAccess(disk, broker, "reader", roots=("allowed",))

    assert access.read_text("allowed/read.txt") == "ok"
    with pytest.raises(PermissionDeniedError):
        access.read_text("outside.txt")
    with pytest.raises(PermissionDeniedError):
        access.write_text("allowed/new.txt", "blocked")


def test_primavtodor_read_access_requires_explicit_capability(tmp_path: Path) -> None:
    disk = DiskModule(tmp_path / "disk")
    disk.start()
    module = PrimavtodorModule(disk)
    module.start()

    denied = PermissionBroker()
    denied.register(manifest("ai", "disk.read"))
    denied_access = PrimavtodorReadAccess(module, denied, "ai")

    with pytest.raises(PermissionDeniedError):
        denied_access.list_records("vehicles")

    allowed = PermissionBroker()
    allowed.register(manifest("ai", "primavtodor.read"))
    allowed_access = PrimavtodorReadAccess(module, allowed, "ai")

    assert allowed_access.list_records("vehicles")["records"] == []


class StubPrimavtodor:
    def list_records(self, kind: str) -> dict[str, object]:
        return {
            "kind": kind,
            "records": [
                {
                    "id": "emp-1",
                    "values": {
                        "full_name": "Иван Иванов",
                        "phone": "+79991234567",
                        "personnel_number": "000123",
                        "fuel_card_number": "1234567890123456",
                    },
                    "computed": {"driver_card": "1234567890123456"},
                }
            ],
            "problems": [],
        }

    def get_record(self, kind: str, record_id: str) -> dict[str, object]:
        return {"kind": kind, "id": record_id, "card_number": "9999888877776666"}

    def timesheet(self, month: str) -> dict[str, object]:
        return {"month": month, "rows": []}

    def settings(self) -> dict[str, object]:
        return {"season": "summer"}

    def list_documents(self, section_id: str, *, limit: int = 10) -> list[dict[str, object]]:
        return [
            {
                "section_id": section_id,
                "section_title": "Служебные записки",
                "name": "записка-12.md",
                "path": "projects/work/Примавтодор/Служебные записки/записка-12.md",
                "size": 321,
                "extension": "md",
            }
        ][:limit]


def test_ai_tools_mask_sensitive_fields_and_write_audit(tmp_path: Path) -> None:
    disk = DiskModule(tmp_path / "disk")
    disk.start()
    tools = AiToolRegistry(StubPrimavtodor(), AuditLog(disk))  # type: ignore[arg-type]

    payload = json.loads(tools.execute("primavtodor_list_records", {"kind": "employees"}))
    values = payload["records"][0]["values"]

    assert values["full_name"] == "Иван Иванов"
    assert values["phone"] == "***4567"
    assert values["personnel_number"] == "***0123"
    assert values["fuel_card_number"] == "***3456"
    assert payload["records"][0]["computed"]["driver_card"] == "***3456"
    assert not any("write" in name or "delete" in name for name in tools.names)

    events = list((tmp_path / "disk" / "system" / "audit").rglob("*.json"))
    assert len(events) == 1
    audit = json.loads(events[0].read_text(encoding="utf-8"))
    assert audit["subject"] == "ai"
    assert audit["action"] == "primavtodor_list_records"
    assert audit["outcome"] == "allowed"
    serialized = events[0].read_text(encoding="utf-8")
    assert "Иван Иванов" not in serialized
    assert "1234567890123456" not in serialized



def test_ai_document_tool_exposes_metadata_only(tmp_path: Path) -> None:
    disk = DiskModule(tmp_path / "disk")
    disk.start()
    tools = AiToolRegistry(StubPrimavtodor(), AuditLog(disk))  # type: ignore[arg-type]

    names = {item["function"]["name"] for item in tools.definitions("Покажи служебные документы")}
    assert "primavtodor_list_documents" in names
    assert "primavtodor_read_document" not in names
    assert "primavtodor_read_document" not in tools.names

    payload = json.loads(
        tools.execute(
            "primavtodor_list_documents",
            {"section_id": "memos", "limit": 5},
            "Покажи служебные документы",
        )
    )
    assert payload["documents"][0]["name"] == "записка-12.md"
    assert "preview" not in payload["documents"][0]
    assert "content" not in payload["documents"][0]

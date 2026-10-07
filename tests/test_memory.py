import json
from pathlib import Path

import pytest

from yukiyasha.modules.ai.tools import AiToolRegistry
from yukiyasha.modules.audit import AuditLog
from yukiyasha.modules.disk import DiskModule
from yukiyasha.modules.manifest import ModuleManifest
from yukiyasha.modules.memory import (
    MemoryAccess,
    MemoryModule,
    MemoryNotFoundError,
    MemoryValidationError,
)
from yukiyasha.modules.permissions import PermissionBroker, PermissionDeniedError


def _manifest(module_id: str, *permissions: str) -> ModuleManifest:
    return ModuleManifest(
        module_id=module_id,
        name=module_id,
        version="test",
        description="test",
        permissions=permissions,
    )


def test_memory_lifecycle_remember_search_deduplicate_and_forget(tmp_path: Path) -> None:
    disk = DiskModule(tmp_path / "disk")
    disk.start()
    memory = MemoryModule(disk)
    memory.start()

    first = memory.remember("Пользователь предпочитает тёмную тему")
    duplicate = memory.remember("  Пользователь   предпочитает тёмную тему  ")
    second = memory.remember("Любимый редактор — VS Code")

    assert duplicate["id"] == first["id"]
    assert len(memory.list_items()) == 2
    assert [item["id"] for item in memory.search("какую тему предпочитает пользователь")] == [
        first["id"]
    ]
    assert [item["id"] for item in memory.search("редактор VS Code")] == [second["id"]]

    memory.forget(str(first["id"]))
    assert [item["id"] for item in memory.list_items()] == [second["id"]]
    with pytest.raises(MemoryNotFoundError):
        memory.forget(str(first["id"]))

    memory.stop()


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "Запомни мой пароль: hunter2",
        "API key sk-test-123",
        "access token abcdef",
    ],
)
def test_memory_rejects_empty_or_secret_material(tmp_path: Path, text: str) -> None:
    disk = DiskModule(tmp_path / "disk")
    disk.start()
    memory = MemoryModule(disk)
    memory.start()

    with pytest.raises(MemoryValidationError):
        memory.remember(text)

    assert memory.list_items() == []


def test_memory_access_is_default_deny_per_operation(tmp_path: Path) -> None:
    disk = DiskModule(tmp_path / "disk")
    disk.start()
    memory = MemoryModule(disk)
    memory.start()
    stored = memory.remember("Пользователь любит короткие ответы")

    broker = PermissionBroker()
    broker.register(_manifest("reader", "memory.read"))
    reader = MemoryAccess(memory, broker, "reader")

    assert reader.search("короткие ответы")[0]["id"] == stored["id"]
    with pytest.raises(PermissionDeniedError):
        reader.remember("Нельзя записать")
    with pytest.raises(PermissionDeniedError):
        reader.forget(str(stored["id"]))


class StubPrimavtodor:
    def list_records(self, kind: str) -> dict[str, object]:
        return {"kind": kind, "records": [], "problems": []}

    def get_record(self, kind: str, record_id: str) -> dict[str, object]:
        return {"kind": kind, "id": record_id}

    def timesheet(self, month: str) -> dict[str, object]:
        return {"month": month, "rows": []}

    def settings(self) -> dict[str, object]:
        return {"season": "summer"}


def _ai_tools(tmp_path: Path) -> tuple[AiToolRegistry, MemoryModule]:
    disk = DiskModule(tmp_path / "disk")
    disk.start()
    memory = MemoryModule(disk)
    memory.start()

    broker = PermissionBroker()
    broker.register(_manifest("ai", "memory.read", "memory.write", "memory.delete"))
    access = MemoryAccess(memory, broker, "ai")
    tools = AiToolRegistry(
        StubPrimavtodor(),  # type: ignore[arg-type]
        AuditLog(disk),
        access,
    )
    return tools, memory


def test_memory_tools_are_exposed_only_for_relevant_explicit_intent(tmp_path: Path) -> None:
    tools, _ = _ai_tools(tmp_path)

    assert tools.definitions("Привет") == []

    remember = {
        item["function"]["name"] for item in tools.definitions("Запомни, что я люблю тёмную тему")
    }
    recall = {
        item["function"]["name"] for item in tools.definitions(
            "Помнишь, какой редактор мне нравится?"
        )
    }
    forget = {
        item["function"]["name"] for item in tools.definitions("Забудь эту запись")
    }

    assert remember == {"memory_search", "memory_remember"}
    assert recall == {"memory_search"}
    assert forget == {"memory_search", "memory_forget"}


def test_memory_mutation_requires_explicit_user_word_and_audits_without_content(
    tmp_path: Path,
) -> None:
    tools, memory = _ai_tools(tmp_path)
    text = "Пользователь предпочитает короткие ответы"

    denied = json.loads(tools.execute("memory_remember", {"text": text}, "Мне нравятся ответы"))
    assert denied["error"]
    assert memory.list_items() == []

    saved = json.loads(
        tools.execute("memory_remember", {"text": text}, "Запомни, что я люблю короткие ответы")
    )
    assert saved["id"].startswith("mem-")
    assert memory.list_items()[0]["text"] == text

    found = json.loads(
        tools.execute(
            "memory_search",
            {"query": "короткие ответы", "limit": 3},
            "Помнишь, как я люблю получать ответы?",
        )
    )
    assert found["count"] == 1
    assert found["memories"][0]["id"] == saved["id"]

    refused_forget = json.loads(
        tools.execute("memory_forget", {"query": "короткие ответы"}, "Что там в памяти?")
    )
    assert refused_forget["error"]
    assert len(memory.list_items()) == 1

    forgotten = json.loads(
        tools.execute(
            "memory_forget",
            {"query": "короткие ответы"},
            "Забудь, что я люблю короткие ответы",
        )
    )
    assert forgotten["status"] == "forgotten"
    assert memory.list_items() == []

    audit_files = list((tmp_path / "disk" / "system" / "audit").rglob("*.json"))
    assert len(audit_files) == 5
    audit_text = "\n".join(path.read_text(encoding="utf-8") for path in audit_files)
    assert text not in audit_text
    assert "короткие ответы" not in audit_text
    assert '"query_logged": false' in audit_text


def test_memory_tool_cannot_store_a_secret_even_on_explicit_request(tmp_path: Path) -> None:
    tools, memory = _ai_tools(tmp_path)

    result = json.loads(
        tools.execute(
            "memory_remember",
            {"text": "Мой пароль: hunter2"},
            "Запомни мой пароль",
        )
    )

    assert "error" in result
    assert "Пароли" in result["error"]
    assert memory.list_items() == []



def test_forget_matching_refuses_ambiguous_memory(tmp_path: Path) -> None:
    disk = DiskModule(tmp_path / "disk")
    disk.start()
    memory = MemoryModule(disk)
    memory.start()
    memory.remember("Пользователь любит короткие ответы")
    memory.remember("Пользователь любит короткие отчёты")

    with pytest.raises(MemoryValidationError):
        memory.forget_matching("пользователь любит короткие")

    assert len(memory.list_items()) == 2

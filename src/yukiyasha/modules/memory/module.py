"""Persistent, explicit long-term memory for the Yukiyasha assistant."""

import json
import re
import uuid
from datetime import UTC, datetime

from yukiyasha.modules.disk import DiskConflictError, DiskModule
from yukiyasha.modules.disk.access import DiskAccess
from yukiyasha.modules.manifest import ModuleManifest
from yukiyasha.modules.memory.errors import (
    MemoryLimitError,
    MemoryNotFoundError,
    MemoryValidationError,
)
from yukiyasha.modules.registry import ModuleState
from yukiyasha.version import get_version

MEMORY_DIR = "memory"
ITEMS_DIR = f"{MEMORY_DIR}/items"
MEMORY_ID_RE = re.compile(r"^mem-[0-9a-f]{12}$")
MAX_MEMORY_CHARS = 2_000
MAX_MEMORY_ITEMS = 500
MAX_SEARCH_RESULTS = 10
TOKEN_RE = re.compile(r"[\wа-яё-]{2,}", re.IGNORECASE)

MEMORY_MANIFEST = ModuleManifest(
    module_id="memory",
    name="Память",
    version=get_version(),
    description=(
        "Локальная долговременная память помощницы. Записи создаются и удаляются только "
        "через явные memory-capabilities и хранятся отдельно от диалогов."
    ),
    permissions=("disk.read", "disk.write", "disk.delete"),
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _tokens(text: str) -> set[str]:
    return {token.casefold() for token in TOKEN_RE.findall(text)}


class MemoryModule:
    manifest = MEMORY_MANIFEST

    def __init__(self, disk: DiskModule | DiskAccess) -> None:
        self._disk = disk
        self._state = ModuleState.REGISTERED
        self._last_error: str | None = None

    @property
    def state(self) -> ModuleState:
        return self._state

    def start(self) -> None:
        self._disk.make_dir(ITEMS_DIR)
        self._last_error = None
        self._state = ModuleState.READY

    def stop(self) -> None:
        self._state = ModuleState.STOPPED

    def fail(self, error: BaseException) -> None:
        self._last_error = str(error)
        self._state = ModuleState.FAILED

    def snapshot(self) -> dict[str, object]:
        health: dict[str, object] = {
            "status": "ok" if self.state is ModuleState.READY else self.state.value,
            "items": len(self.list_items()) if self.state is ModuleState.READY else None,
            "limit": MAX_MEMORY_ITEMS,
        }
        if self._last_error:
            health["error"] = self._last_error
        return {
            "manifest": self.manifest.to_dict(),
            "state": self.state.value,
            "health": health,
        }

    def _path(self, memory_id: str) -> str:
        if not MEMORY_ID_RE.fullmatch(memory_id):
            raise MemoryNotFoundError("Запись памяти не найдена")
        return f"{ITEMS_DIR}/{memory_id}.json"

    def _load(self, memory_id: str) -> dict[str, object]:
        try:
            payload = json.loads(self._disk.read_text(self._path(memory_id)))
        except (FileNotFoundError, ValueError):
            raise MemoryNotFoundError("Запись памяти не найдена") from None
        if not isinstance(payload, dict) or payload.get("id") != memory_id:
            raise MemoryNotFoundError("Запись памяти повреждена или не найдена")
        return payload

    def list_items(self) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        for entry in self._disk.list_entries(ITEMS_DIR):
            name = str(entry["name"])
            if entry["type"] != "file" or not name.endswith(".json"):
                continue
            memory_id = name.removesuffix(".json")
            if not MEMORY_ID_RE.fullmatch(memory_id):
                continue
            try:
                items.append(self._load(memory_id))
            except MemoryNotFoundError:
                continue
        items.sort(key=lambda item: str(item.get("updated_at", "")), reverse=True)
        return items

    def remember(self, text: str) -> dict[str, object]:
        clean = " ".join(text.split())
        if not clean:
            raise MemoryValidationError("Нечего запоминать")
        if len(clean) > MAX_MEMORY_CHARS:
            raise MemoryValidationError(
                f"Запись памяти длиннее {MAX_MEMORY_CHARS} символов"
            )
        if SECRET_RE.search(clean):
            raise MemoryValidationError(
                "Пароли, API-ключи и токены нельзя сохранять в долговременную память"
            )

        existing = self.list_items()
        normalized = clean.casefold()
        for item in existing:
            if str(item.get("text", "")).casefold() == normalized:
                return item
        if len(existing) >= MAX_MEMORY_ITEMS:
            raise MemoryLimitError("Лимит долговременной памяти исчерпан")

        now = _now()
        item: dict[str, object] = {
            "id": f"mem-{uuid.uuid4().hex[:12]}",
            "text": clean,
            "created_at": now,
            "updated_at": now,
        }
        self._disk.write_text(
            self._path(str(item["id"])),
            json.dumps(item, ensure_ascii=False, indent=2) + "\n",
            overwrite=False,
        )
        return item

    def forget(self, memory_id: str) -> None:
        self._load(memory_id)
        self._disk.delete(self._path(memory_id))

    def search(self, query: str, *, limit: int = 5) -> list[dict[str, object]]:
        wanted = _tokens(query)
        if not wanted:
            return []
        limit = max(1, min(limit, MAX_SEARCH_RESULTS))
        ranked: list[tuple[int, str, dict[str, object]]] = []
        for item in self.list_items():
            text = str(item.get("text", ""))
            overlap = len(wanted & _tokens(text))
            if overlap:
                ranked.append((overlap, str(item.get("updated_at", "")), item))
        ranked.sort(key=lambda row: (row[0], row[1]), reverse=True)
        return [item for _, _, item in ranked[:limit]]

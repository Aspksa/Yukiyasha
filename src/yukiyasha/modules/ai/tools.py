"""Guarded local tools exposed to the AI assistant."""

import json
import re
from collections.abc import Callable
from typing import Any

from yukiyasha.modules.audit import AuditLog
from yukiyasha.modules.memory import MemoryAccess, MemoryError
from yukiyasha.modules.permissions import PermissionDeniedError
from yukiyasha.modules.primavtodor.access import PrimavtodorReadAccess
from yukiyasha.modules.primavtodor.errors import PrimavtodorError

SENSITIVE_KEYS = {
    "phone",
    "personnel_number",
    "fuel_card_number",
    "card_number",
    "driver_card",
}
BUSINESS_TRIGGER = re.compile(
    r"примавтодор|путев|водител|сотрудник|машин|автомоб|гараж|гсм|топлив|заправ|"
    r"табел|пробег|расход|норм[аы]|одометр",
    re.IGNORECASE,
)
MEMORY_TRIGGER = re.compile(
    r"запомни|забудь|помнишь|вспомни|мы говорили|раньше|предпочита|нравит|люблю|"
    r"как меня зовут|что ты знаешь обо мне|моя? привычк|мой выбор|мо[ия] настройк",
    re.IGNORECASE,
)
REMEMBER_TRIGGER = re.compile(
    r"\bзапомни\b|\bсохрани (?:это|в память)\b|\bпомни,? что\b",
    re.IGNORECASE,
)
FORGET_TRIGGER = re.compile(
    r"\bзабудь\b|\bудали (?:это )?из памяти\b|\bне помни\b",
    re.IGNORECASE,
)
KINDS = ("waybills", "fuel", "employees", "vehicles")
MAX_LIST_ITEMS = 20
MAX_TIMESHEET_ROWS = 20
MAX_MEMORY_RESULTS = 8


def _masked(value: Any, key: str | None = None) -> Any:
    if key in SENSITIVE_KEYS and value not in (None, ""):
        text = str(value)
        return f"***{text[-4:]}" if len(text) > 4 else "***"
    if isinstance(value, dict):
        return {name: _masked(item, name) for name, item in value.items()}
    if isinstance(value, list):
        return [_masked(item) for item in value]
    return value


class AiToolRegistry:
    """Tool definitions + guarded execution over explicit runtime capabilities."""

    def __init__(
        self,
        primavtodor: PrimavtodorReadAccess,
        audit: AuditLog,
        memory: MemoryAccess | None = None,
    ) -> None:
        self._primavtodor = primavtodor
        self._memory = memory
        self._audit = audit
        self._handlers: dict[str, Callable[[dict[str, object]], object]] = {
            "primavtodor_list_records": self._list_records,
            "primavtodor_get_record": self._get_record,
            "primavtodor_timesheet": self._timesheet,
            "primavtodor_settings": self._settings,
        }
        if memory is not None:
            self._handlers.update(
                {
                    "memory_search": self._memory_search,
                    "memory_remember": self._memory_remember,
                    "memory_forget": self._memory_forget,
                }
            )

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._handlers)

    def might_need_tools(self, message: str) -> bool:
        return bool(BUSINESS_TRIGGER.search(message) or MEMORY_TRIGGER.search(message))

    def definitions(self, message: str = "") -> list[dict[str, object]]:
        definitions: list[dict[str, object]] = []
        if BUSINESS_TRIGGER.search(message):
            definitions.extend(self._business_definitions())
        if self._memory is not None and MEMORY_TRIGGER.search(message):
            definitions.append(self._memory_search_definition())
            if REMEMBER_TRIGGER.search(message):
                definitions.append(self._memory_remember_definition())
            if FORGET_TRIGGER.search(message):
                definitions.append(self._memory_forget_definition())
        return definitions

    def execute(
        self,
        name: str,
        arguments: dict[str, object],
        user_message: str = "",
    ) -> str:
        handler = self._handlers.get(name)
        if handler is None:
            return json.dumps({"error": "Неизвестный инструмент"}, ensure_ascii=False)

        if name == "memory_remember" and not REMEMBER_TRIGGER.search(user_message):
            return self._denied(name, {"reason": "no_explicit_remember"})
        if name == "memory_forget" and not FORGET_TRIGGER.search(user_message):
            return self._denied(name, {"reason": "no_explicit_forget"})

        metadata = self._audit_metadata(name, arguments)
        try:
            result = handler(arguments)
            self._audit.record(
                subject="ai",
                action=name,
                outcome="allowed",
                metadata=metadata,
            )
        except PermissionDeniedError:
            return self._denied(name, metadata)
        except (PrimavtodorError, MemoryError, RuntimeError, ValueError) as exc:
            self._audit.record(
                subject="ai",
                action=name,
                outcome="error",
                metadata={**metadata, "error_type": type(exc).__name__},
            )
            return json.dumps({"error": str(exc)}, ensure_ascii=False)
        return json.dumps(_masked(result), ensure_ascii=False, separators=(",", ":"))

    def _denied(self, name: str, metadata: dict[str, object]) -> str:
        self._audit.record(
            subject="ai",
            action=name,
            outcome="denied",
            metadata=metadata,
        )
        return json.dumps({"error": "Доступ к действию запрещён"}, ensure_ascii=False)

    def _audit_metadata(
        self, name: str, arguments: dict[str, object]
    ) -> dict[str, object]:
        allowed = {"kind", "record_id", "month", "employee_id", "limit"}
        metadata = {key: value for key, value in arguments.items() if key in allowed}
        if name == "memory_remember":
            metadata["content_stored"] = True
        if name in {"memory_search", "memory_forget"}:
            metadata["query_logged"] = False
        return metadata

    def _business_definitions(self) -> list[dict[str, object]]:
        kind_schema = {"type": "string", "enum": list(KINDS)}
        return [
            {
                "type": "function",
                "function": {
                    "name": "primavtodor_list_records",
                    "description": (
                        "Показать последние записи Примавтодора: путевые листы, ГСМ, "
                        "сотрудники или машины. Только чтение."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "kind": kind_schema,
                            "limit": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": MAX_LIST_ITEMS,
                            },
                        },
                        "required": ["kind"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "primavtodor_get_record",
                    "description": "Получить одну запись Примавтодора по её id. Только чтение.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "kind": kind_schema,
                            "record_id": {"type": "string"},
                        },
                        "required": ["kind", "record_id"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "primavtodor_timesheet",
                    "description": (
                        "Получить табель за месяц ГГГГ-ММ. По умолчанию возвращаются итоги "
                        "по сотрудникам; можно запросить одного сотрудника."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "month": {"type": "string", "pattern": "^\\d{4}-\\d{2}$"},
                            "employee_id": {"type": "string"},
                        },
                        "required": ["month"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "primavtodor_settings",
                    "description": (
                        "Получить текущий сезон и настройки Примавтодора. Только чтение."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                },
            },
        ]

    def _memory_search_definition(self) -> dict[str, object]:
        return {
            "type": "function",
            "function": {
                "name": "memory_search",
                "description": (
                    "Найти релевантные записи долговременной памяти пользователя. "
                    "Используй только когда вопрос зависит от ранее сохранённых предпочтений "
                    "или фактов."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": MAX_MEMORY_RESULTS,
                        },
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
        }

    def _memory_remember_definition(self) -> dict[str, object]:
        return {
            "type": "function",
            "function": {
                "name": "memory_remember",
                "description": (
                    "Сохранить короткий устойчивый факт или предпочтение в долговременную память. "
                    "Разрешено только когда пользователь прямо попросил запомнить. Не сохраняй "
                    "пароли, ключи, токены и случайные детали диалога."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                    "additionalProperties": False,
                },
            },
        }

    def _memory_forget_definition(self) -> dict[str, object]:
        return {
            "type": "function",
            "function": {
                "name": "memory_forget",
                "description": (
                    "Удалить конкретную запись памяти. Разрешено только когда пользователь "
                    "прямо попросил забыть или удалить её."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
        }

    def _kind(self, arguments: dict[str, object]) -> str:
        kind = str(arguments.get("kind", ""))
        if kind not in KINDS:
            raise ValueError("Неизвестный тип данных")
        return kind

    def _list_records(self, arguments: dict[str, object]) -> dict[str, object]:
        kind = self._kind(arguments)
        raw_limit = arguments.get("limit", MAX_LIST_ITEMS)
        limit = max(1, min(int(raw_limit), MAX_LIST_ITEMS))
        result = self._primavtodor.list_records(kind)
        records = result.get("records")
        items = records if isinstance(records, list) else []
        return {
            "kind": kind,
            "count": len(items),
            "records": items[:limit],
            "truncated": len(items) > limit,
            "problems": result.get("problems", []),
        }

    def _get_record(self, arguments: dict[str, object]) -> dict[str, object]:
        return self._primavtodor.get_record(
            self._kind(arguments),
            str(arguments.get("record_id", "")),
        )

    def _timesheet(self, arguments: dict[str, object]) -> dict[str, object]:
        month = str(arguments.get("month", ""))
        view = self._primavtodor.timesheet(month)
        wanted = str(arguments.get("employee_id", ""))
        rows = view.get("rows")
        source = rows if isinstance(rows, list) else []
        if wanted:
            source = [row for row in source if str(row.get("employee_id")) == wanted]
        source = source[:MAX_TIMESHEET_ROWS]
        return {
            "month": view.get("month"),
            "rows": [
                {
                    "employee_id": row.get("employee_id"),
                    "name": row.get("name"),
                    "position": row.get("position"),
                    "totals": row.get("totals"),
                    "cells": row.get("cells") if wanted else None,
                }
                for row in source
                if isinstance(row, dict)
            ],
        }

    def _settings(self, arguments: dict[str, object]) -> dict[str, object]:
        del arguments
        return self._primavtodor.settings()

    def _memory_search(self, arguments: dict[str, object]) -> dict[str, object]:
        assert self._memory is not None
        query = str(arguments.get("query", "")).strip()
        if not query:
            raise ValueError("Пустой запрос к памяти")
        limit = max(1, min(int(arguments.get("limit", 5)), MAX_MEMORY_RESULTS))
        items = self._memory.search(query, limit=limit)
        return {"count": len(items), "memories": items}

    def _memory_remember(self, arguments: dict[str, object]) -> dict[str, object]:
        assert self._memory is not None
        item = self._memory.remember(str(arguments.get("text", "")))
        return {"status": "remembered", "id": item["id"]}

    def _memory_forget(self, arguments: dict[str, object]) -> dict[str, object]:
        assert self._memory is not None
        query = str(arguments.get("query", "")).strip()
        if not query:
            raise ValueError("Пустой запрос на удаление памяти")
        memory_id = self._memory.forget_matching(query)
        return {"status": "forgotten", "id": memory_id}

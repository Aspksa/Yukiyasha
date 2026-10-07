"""Read-only local tools exposed to the AI assistant."""

import json
import re
from collections.abc import Callable
from typing import Any

from yukiyasha.modules.audit import AuditLog
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
TOOL_TRIGGER = re.compile(
    r"примавтодор|путев|водител|сотрудник|машин|автомоб|гараж|гсм|топлив|заправ|"
    r"табел|пробег|расход|норм[аы]|одометр",
    re.IGNORECASE,
)
KINDS = ("waybills", "fuel", "employees", "vehicles")
MAX_LIST_ITEMS = 20
MAX_TIMESHEET_ROWS = 20


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
    """Tool definitions + guarded execution. No mutating tool is registered."""

    def __init__(self, primavtodor: PrimavtodorReadAccess, audit: AuditLog) -> None:
        self._primavtodor = primavtodor
        self._audit = audit
        self._handlers: dict[str, Callable[[dict[str, object]], object]] = {
            "primavtodor_list_records": self._list_records,
            "primavtodor_get_record": self._get_record,
            "primavtodor_timesheet": self._timesheet,
            "primavtodor_settings": self._settings,
        }

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._handlers)

    def might_need_tools(self, message: str) -> bool:
        return bool(TOOL_TRIGGER.search(message))

    def definitions(self) -> list[dict[str, object]]:
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
                            "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIST_ITEMS},
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
                    "description": "Получить текущий сезон и настройки Примавтодора. Только чтение.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                },
            },
        ]

    def execute(self, name: str, arguments: dict[str, object]) -> str:
        handler = self._handlers.get(name)
        if handler is None:
            return json.dumps({"error": "Неизвестный инструмент"}, ensure_ascii=False)
        metadata = {
            key: value
            for key, value in arguments.items()
            if key in {"kind", "record_id", "month", "employee_id", "limit"}
        }
        try:
            result = handler(arguments)
            # Fail closed: data is returned only after the disclosure was successfully audited.
            self._audit.record(
                subject="ai",
                action=name,
                outcome="allowed",
                metadata=metadata,
            )
        except PermissionDeniedError:
            self._audit.record(
                subject="ai",
                action=name,
                outcome="denied",
                metadata=metadata,
            )
            return json.dumps({"error": "Доступ к данным запрещён"}, ensure_ascii=False)
        except (PrimavtodorError, RuntimeError, ValueError) as exc:
            self._audit.record(
                subject="ai",
                action=name,
                outcome="error",
                metadata={**metadata, "error_type": type(exc).__name__},
            )
            return json.dumps({"error": str(exc)}, ensure_ascii=False)
        return json.dumps(_masked(result), ensure_ascii=False, separators=(",", ":"))

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

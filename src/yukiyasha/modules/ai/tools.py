"""Guarded local tools exposed to the AI assistant."""

import json
import re
from collections.abc import Callable
from datetime import date
from typing import Any

from yukiyasha.modules.audit import AuditLog
from yukiyasha.modules.memory import MemoryAccess, MemoryError
from yukiyasha.modules.permissions import PermissionDeniedError
from yukiyasha.modules.primavtodor.access import PrimavtodorReadAccess
from yukiyasha.modules.primavtodor.errors import PrimavtodorError
from yukiyasha.modules.proposals import ProposalCreateAccess, ProposalError

SENSITIVE_KEYS = {
    "phone",
    "personnel_number",
    "fuel_card_number",
    "card_number",
    "driver_card",
}
DOCUMENT_TRIGGER = re.compile(
    r"документ|договор|сч[её]т|оферт|служебн|записк|приказ|распоряж",
    re.IGNORECASE,
)
# verbs that book, move or cancel a trip; both the mutation gate and the terse-order route use them
BOOKING_VERBS = (
    "запиши|поставь|отметь|запланируй|забронируй|перенеси|перенес[её]м|сдвинь|продли|сократи|"
    "отмени|убери"
)
BUSINESS_TRIGGER = re.compile(
    r"примавтодор|путев|водител|сотрудник|машин|автомоб|гараж|гсм|топлив|заправ|"
    r"табел|пробег|расход|норм[аы]|одометр|документ|договор|сч[её]т|оферт|служебн|"
    r"записк|приказ|распоряж|график|командиров|свободн|отъезд|выезд|больнич|отпуск|"
    r"сводк|занят|поездк|брон|"
    # «Запиши Веровского 7-9»: a short booking order has a name and a date, nothing else
    r"\b(?:" + BOOKING_VERBS + r")(?:\s+\S+){1,4}?\s+(?:с\s+|до\s+|на\s+)?"
    r"(?:\d{1,2}\b|сегодня|завтра|послезавтра)",
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
MUTATION_TRIGGER = re.compile(
    r"создай|добавь|измени|обнови|исправь|удали|оформи|закрой|назначь|"
    + BOOKING_VERBS
    + r"|предложи измен|подготовь измен",
    re.IGNORECASE,
)
KINDS = ("waybills", "fuel", "employees", "vehicles")
PROPOSAL_KINDS = (*KINDS, "bookings")  # bookings = the vehicle schedule
DOCUMENT_SECTIONS = ("contracts", "invoice_offer", "memos", "orders", "directives")
MAX_LIST_ITEMS = 20
MAX_TIMESHEET_ROWS = 20
MAX_MEMORY_RESULTS = 8


def _int(arguments: dict[str, object], key: str, default: int, low: int, high: int) -> int:
    """An optional integer argument: missing, null or not a number means the default."""
    try:
        value = int(arguments.get(key))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(low, min(value, high))


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
        proposals: ProposalCreateAccess | None = None,
    ) -> None:
        self._primavtodor = primavtodor
        self._memory = memory
        self._proposals = proposals
        self._audit = audit
        self._handlers: dict[str, Callable[[dict[str, object]], object]] = {
            "primavtodor_list_records": self._list_records,
            "primavtodor_get_record": self._get_record,
            "primavtodor_timesheet": self._timesheet,
            "primavtodor_settings": self._settings,
            "primavtodor_month_review": self._month_review,
            "primavtodor_briefing": self._briefing,
            "primavtodor_schedule": self._schedule,
            "primavtodor_parse_booking": self._parse_booking,
            "primavtodor_list_documents": self._list_documents,
        }
        if proposals is not None:
            self._handlers["primavtodor_propose_change"] = self._propose_change
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
            if DOCUMENT_TRIGGER.search(message):
                definitions.extend(self._document_definitions())
            if self._proposals is not None and MUTATION_TRIGGER.search(message):
                definitions.append(self._proposal_definition())
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
        if name == "primavtodor_propose_change" and not (
            BUSINESS_TRIGGER.search(user_message) and MUTATION_TRIGGER.search(user_message)
        ):
            return self._denied(name, {"reason": "no_mutation_intent"})

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
        except (PrimavtodorError, MemoryError, ProposalError, RuntimeError, ValueError) as exc:
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
        allowed = {
            "kind", "record_id", "month", "employee_id", "section_id", "limit", "day", "days",
        }  # fmt: skip
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
                    "name": "primavtodor_month_review",
                    "description": (
                        "Контроль месяца ГГГГ-ММ: готовность шагов (путевые листы, заправки, "
                        "табель) и замечания по расходу топлива: перерасход, разрывы пробега, "
                        "не то топливо, незакрытые листы. Только чтение."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "month": {"type": "string", "pattern": "^\\d{4}-\\d{2}$"},
                        },
                        "required": ["month"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "primavtodor_briefing",
                    "description": (
                        "Сводка на сегодня: кто в отъезде, кто выезжает завтра, больничные и "
                        "отпуска, незакрытые путевые листы, выписки во «Входящих», замечания "
                        "месяца. Только чтение."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "primavtodor_schedule",
                    "description": (
                        "График машин: выезды (водитель, машина, даты, тип) и кто свободен в "
                        "выбранный день, кто на больничном или в отпуске по табелю. "
                        "Только чтение."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "day": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
                            "days": {"type": "integer", "minimum": 1, "maximum": 31},
                        },
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "primavtodor_parse_booking",
                    "description": (
                        "Разобрать фразу вроде «Веровский 7-9 командировка Находка» в выезд: "
                        "водитель, машина, даты, тип и что осталось неясным. Ничего не "
                        "сохраняет; для записи затем создай предложение изменения "
                        "(kind=bookings) из полученных values."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {"text": {"type": "string", "maxLength": 300}},
                        "required": ["text"],
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

    def _document_definitions(self) -> list[dict[str, object]]:
        section_schema = {"type": "string", "enum": list(DOCUMENT_SECTIONS)}
        return [
            {
                "type": "function",
                "function": {
                    "name": "primavtodor_list_documents",
                    "description": (
                        "Показать документы выбранного раздела Примавтодора. Только чтение."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "section_id": section_schema,
                            "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                        },
                        "required": ["section_id"],
                        "additionalProperties": False,
                    },
                },
            },
        ]

    def _proposal_definition(self) -> dict[str, object]:
        return {
            "type": "function",
            "function": {
                "name": "primavtodor_propose_change",
                "description": (
                    "Создать предложение изменения Примавтодора. Это НЕ применяет изменение. "
                    "Пользователь должен отдельно подтвердить proposal по его id."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["create", "update", "delete"],
                        },
                        "kind": {"type": "string", "enum": list(PROPOSAL_KINDS)},
                        "record_id": {"type": "string"},
                        "payload": {
                            "type": "object",
                            "description": (
                                "Значения полей. Для kind=bookings: vehicle_id, driver_id, "
                                "date_from, date_to (ГГГГ-ММ-ДД), kind (trip | busy | service), "
                                "note; готовые значения даёт primavtodor_parse_booking."
                            ),
                        },
                        "reason": {"type": "string"},
                    },
                    "required": ["operation", "kind"],
                    "additionalProperties": False,
                },
            },
        }

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
        limit = _int(arguments, "limit", MAX_LIST_ITEMS, 1, MAX_LIST_ITEMS)
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

    def _month_review(self, arguments: dict[str, object]) -> dict[str, object]:
        review = self._primavtodor.month_review(str(arguments.get("month", "")))
        findings = review.get("findings")
        shown = findings if isinstance(findings, list) else []
        return {
            "month": review.get("month"),
            "ready": review.get("ready"),
            "steps": review.get("steps"),
            "counts": review.get("counts"),
            "findings": [
                {key: item.get(key) for key in ("severity", "title", "detail", "date", "subject")}
                for item in shown[:MAX_LIST_ITEMS]
                if isinstance(item, dict)
            ],
            "more": max(0, len(shown) - MAX_LIST_ITEMS),
        }

    def _settings(self, arguments: dict[str, object]) -> dict[str, object]:
        del arguments
        return self._primavtodor.settings()

    def _list_documents(self, arguments: dict[str, object]) -> dict[str, object]:
        section_id = str(arguments.get("section_id", ""))
        if section_id not in DOCUMENT_SECTIONS:
            raise ValueError("Неизвестный раздел документов")
        limit = _int(arguments, "limit", 10, 1, 20)
        documents = self._primavtodor.list_documents(section_id, limit=limit)
        return {"section_id": section_id, "documents": documents}

    def _briefing(self, arguments: dict[str, object]) -> dict[str, object]:
        del arguments
        return self._primavtodor.briefing()

    def _schedule(self, arguments: dict[str, object]) -> dict[str, object]:
        raw_day = str(arguments.get("day") or "")
        day = date.fromisoformat(raw_day) if raw_day else None
        days = _int(arguments, "days", 7, 1, 31)
        view = self._primavtodor.schedule(day, days)
        keep = ("id", "vehicle", "driver", "span", "kind_label", "note", "conflicts")
        free = view["free"]
        rows = view["bookings"]
        limit = MAX_LIST_ITEMS * 2
        return {
            "from": view["start"],
            "to": view["end"],
            "bookings_total": len(rows),  # type: ignore[arg-type]
            "bookings_truncated": len(rows) > limit,  # type: ignore[arg-type]
            "bookings": [{key: row[key] for key in keep} for row in rows[:limit]],  # type: ignore[index]
            "free_on": free["day"],  # type: ignore[index]
            "free_vehicles": [
                {"id": v["id"], "plate": v["plate"], "model": v["model"], "next": v["next"]}
                for v in free["vehicles"]  # type: ignore[index]
            ],
            "free_drivers": [
                {"id": d["id"], "name": d["name"], "next": d["next"]}
                for d in free["drivers"]  # type: ignore[index]
            ],
            "absent": free["absent"],  # type: ignore[index]
        }

    def _parse_booking(self, arguments: dict[str, object]) -> dict[str, object]:
        text = str(arguments.get("text", "")).strip()[:300]
        if not text:
            raise ValueError("Пустая фраза")
        return self._primavtodor.parse_booking(text)

    def _propose_change(self, arguments: dict[str, object]) -> dict[str, object]:
        assert self._proposals is not None
        raw_payload = arguments.get("payload")
        payload = raw_payload if isinstance(raw_payload, dict) else None
        reason = str(arguments.get("reason", ""))
        changes = arguments.get("operation") in ("create", "update")
        if changes and arguments.get("kind") == "bookings" and payload:
            # the text to approve describes the booking as it will be after the change
            summary = self._primavtodor.describe_booking(
                payload, str(arguments["record_id"]) if arguments.get("record_id") else None
            )
            reason = f"{summary}. {reason}".strip() if summary else reason
        return self._proposals.create(
            operation=str(arguments.get("operation", "")),
            kind=str(arguments.get("kind", "")),
            record_id=(
                str(arguments["record_id"])
                if arguments.get("record_id") is not None
                else None
            ),
            payload=payload,
            reason=reason,
        )

    def _memory_search(self, arguments: dict[str, object]) -> dict[str, object]:
        assert self._memory is not None
        query = str(arguments.get("query", "")).strip()
        if not query:
            raise ValueError("Пустой запрос к памяти")
        limit = _int(arguments, "limit", 5, 1, MAX_MEMORY_RESULTS)
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

"""The morning summary: what needs attention today, in a few lines with a place to act on each."""

from datetime import date, datetime, timedelta
from typing import Any

from yukiyasha.modules.primavtodor.month_review import build_review
from yukiyasha.modules.primavtodor.records import Records, format_date
from yukiyasha.modules.primavtodor.schema import KIND_EMPLOYEES, KIND_WAYBILLS
from yukiyasha.modules.primavtodor.settings import ModuleSettings
from yukiyasha.modules.primavtodor.timesheet import Timesheet

ERROR, WARN, INFO, OK = "error", "warn", "info", "ok"
_ORDER = {ERROR: 0, WARN: 1, INFO: 2, OK: 3}
MONTH_START_DAYS = 10  # the month just ended is still being closed during its first days
WEEKDAYS = (
    "понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье",
)  # fmt: skip
MONTHS = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)  # fmt: skip


def _plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def _greeting(hour: int) -> str:
    if hour < 5:
        return "Доброй ночи"
    if hour < 12:
        return "Доброе утро"
    if hour < 18:
        return "Добрый день"
    return "Добрый вечер"


def _item(
    item_id: str, severity: str, icon: str, title: str, detail: str, action: dict[str, str]
) -> dict[str, Any]:
    return {
        "id": item_id, "severity": severity, "icon": icon, "title": title,
        "detail": detail, "action": action,
    }  # fmt: skip


def build_briefing(
    data: Records,
    settings: ModuleSettings,
    timesheet: Timesheet,
    bookings_view: dict[str, Any],
    inbox_waiting: int,
    now: datetime,
) -> dict[str, object]:
    today = now.date()
    items: list[dict[str, Any]] = []

    away = bookings_view["now"]
    if away:
        names = ", ".join(
            f"{r['vehicle']} — {r['driver'] or r['kind_label']}" for r in away[:4]
        )
        items.append(
            _item("away", INFO, "trip", f"В отъезде сегодня: {len(away)}", names,
                  {"kind": "schedule"})
        )  # fmt: skip
    tomorrow = (today + timedelta(days=1)).isoformat()
    leaving = [r for r in bookings_view["soon"] if r["date_from"] == tomorrow]
    if leaving:
        names = ", ".join(f"{r['vehicle']} — {r['driver'] or r['kind_label']}" for r in leaving[:4])
        items.append(_item("leaving", INFO, "calendar", f"Завтра выезжают: {len(leaving)}", names,
                           {"kind": "schedule"}))  # fmt: skip
    clashes = [
        r for r in bookings_view["bookings"]
        if r["conflicts"] and r["date_to"] >= today.isoformat()
    ]  # fmt: skip
    if clashes:
        items.append(
            _item("clash", WARN, "warn", f"Пересечения в графике: {len(clashes)}",
                  "Одна машина или один водитель записаны дважды, либо водитель на больничном",
                  {"kind": "schedule"})
        )  # fmt: skip
    for person in bookings_view["absent_now"]:
        items.append(
            _item(f"absent-{person['id']}", INFO, "sick" if person["code"] == "Б" else "leave",
                  f"{person['name']} {person['label']}",
                  f"по табелю до {format_date(person['date_to'])}", {"kind": "schedule"})
        )  # fmt: skip

    drivers = {str(e["id"]): e for e in data.snapshot(KIND_EMPLOYEES)}
    stale = [
        w for w in data.snapshot(KIND_WAYBILLS)
        if w.get("odometer_in") is None and str(w.get("date", "")) < today.isoformat()
        and w.get("driver_id") in drivers
    ]  # fmt: skip
    if stale:
        stale.sort(key=lambda w: str(w.get("date")))
        items.append(
            _item("open-waybills", WARN, "file",
                  f"Не закрыто путевых листов: {len(stale)}",
                  f"Самый старый от {format_date(stale[0].get('date'))}",
                  {"kind": "section", "section": "waybills"})
        )  # fmt: skip

    if inbox_waiting:
        items.append(
            _item("inbox", WARN, "fuel",
                  f"Во «Входящих» ждёт выписок: {inbox_waiting}",
                  "Нажмите, чтобы загрузить", {"kind": "inbox"})
        )  # fmt: skip

    months = [today.strftime("%Y-%m")]
    if today.day <= MONTH_START_DAYS:
        previous = date(today.year, today.month, 1) - timedelta(days=1)
        months.insert(0, previous.strftime("%Y-%m"))
    for month in months:
        review = build_review(data, settings, timesheet, month, today)
        counts = review["counts"]
        issues = counts["error"] + counts["warn"]
        if not issues:
            continue
        severity = ERROR if counts["error"] else WARN
        word = _plural(issues, "замечание", "замечания", "замечаний")
        items.append(
            _item(f"month-{month}", severity, "check", f"Месяц {month}: {issues} {word}",
                  f"ошибок {counts['error']}, к проверке {counts['warn']}",
                  {"kind": "month", "month": month})
        )  # fmt: skip

    items.sort(key=lambda i: _ORDER[i["severity"]])
    needs = sum(1 for i in items if i["severity"] in (ERROR, WARN))
    return {
        "greeting": _greeting(now.hour),
        "date_label": f"{WEEKDAYS[today.weekday()]}, {today.day} {MONTHS[today.month - 1]}",
        "items": items,
        "attention": needs,
        "calm": not items,
    }

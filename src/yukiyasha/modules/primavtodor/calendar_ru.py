"""Production calendar of Russia (производственный календарь) for the years shipped with the app.

The data files (``calendars/ru-<год>.json``) are the open xmlcalendar.ru data compiled from the
government decrees on transfers of days off. In ``days`` of a month every non-working day is
listed: ``N`` a day off (weekend or holiday), ``N+`` a day off that comes from a transfer,
``N*`` a shortened (pre-holiday) working day, one hour shorter. A day that is not listed is an
ordinary working day.
"""

import calendar
import json
from datetime import date
from functools import cache, lru_cache
from importlib import resources

WORK, OFF, SHORT = "work", "off", "short"
STANDARD_HOURS = 8  # a working day at a 40-hour week; a shortened day is one hour less
KIND_LABELS = {WORK: "Рабочий день", OFF: "Выходной / праздничный", SHORT: "Сокращённый день"}
_DIR = resources.files("yukiyasha.modules.primavtodor").joinpath("calendars")


@lru_cache(maxsize=1)
def available_years() -> tuple[int, ...]:
    years = []
    for item in _DIR.iterdir():
        name = item.name
        if name.startswith("ru-") and name.endswith(".json") and name[3:-5].isdigit():
            years.append(int(name[3:-5]))
    return tuple(sorted(years))


@cache
def _load(year: int) -> dict[int, dict[int, tuple[str, bool]]] | None:
    """``{month: {day: (kind, transferred)}}`` of the days that are not ordinary working days."""
    if year not in available_years():
        return None
    data = json.loads(_DIR.joinpath(f"ru-{year}.json").read_text(encoding="utf-8"))
    result: dict[int, dict[int, tuple[str, bool]]] = {}
    for item in data["months"]:
        days: dict[int, tuple[str, bool]] = {}
        for token in str(item["days"]).split(","):
            token = token.strip()
            if not token:
                continue
            kind = SHORT if token.endswith("*") else OFF
            days[int(token.rstrip("+*"))] = (kind, token.endswith("+"))
        result[int(item["month"])] = days
    return result


def has_calendar(year: int) -> bool:
    return year in available_years()


def day_kind(day: date) -> str:
    """``work``, ``off`` or ``short``. Outside the shipped years only weekends are days off."""
    table = _load(day.year)
    if table is None:
        return OFF if day.weekday() >= 5 else WORK
    return table.get(day.month, {}).get(day.day, (WORK, False))[0]


def working_hours(day: date) -> int:
    kind = day_kind(day)
    return 0 if kind == OFF else STANDARD_HOURS - (1 if kind == SHORT else 0)


def month_norm(year: int, month: int) -> dict[str, object]:
    """Working days and hours of a month at a 40-hour week."""
    days = calendar.monthrange(year, month)[1]
    kinds = [day_kind(date(year, month, d)) for d in range(1, days + 1)]
    workdays = sum(1 for k in kinds if k != OFF)
    return {
        "workdays": workdays,
        "short_days": kinds.count(SHORT),
        "days_off": kinds.count(OFF),
        "hours": workdays * STANDARD_HOURS - kinds.count(SHORT),
        "from_calendar": has_calendar(year),
    }


def year_view(year: int) -> dict[str, object] | None:
    """The whole year for the browser: a kind for every day plus the norm of each month."""
    table = _load(year)
    if table is None:
        return None
    months = []
    for month in range(1, 13):
        days_in_month = calendar.monthrange(year, month)[1]
        days = []
        for number in range(1, days_in_month + 1):
            moment = date(year, month, number)
            kind, transferred = table.get(month, {}).get(number, (WORK, False))
            days.append(
                {
                    "day": number,
                    "weekday": moment.weekday(),
                    "kind": kind,
                    "transferred": transferred,
                    "holiday": kind == OFF and moment.weekday() < 5 and not transferred,
                }
            )
        months.append({"month": month, "days": days, "norm": month_norm(year, month)})
    total_days = sum(m["norm"]["workdays"] for m in months)  # type: ignore[index]
    total_hours = sum(m["norm"]["hours"] for m in months)  # type: ignore[index]
    return {"year": year, "months": months, "workdays": total_days, "hours": total_hours}

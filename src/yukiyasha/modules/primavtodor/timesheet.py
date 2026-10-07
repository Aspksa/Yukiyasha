"""Timesheet (табель): computed from waybills plus manual marks stored on the disk.

A day on which a driver has a waybill is a working day ("Я") automatically. Anything else
(leave, sick leave, business trip, ...) is entered by hand and stored per month in
``projects/work/Примавтодор/Табель/<ГГГГ-ММ>.json``. A manual mark overrides the automatic one;
if they contradict each other the cell is flagged as a conflict.
"""

import calendar
import json
from collections import defaultdict
from datetime import date

from yukiyasha.modules.disk import DiskError, DiskModule
from yukiyasha.modules.primavtodor import calendar_ru
from yukiyasha.modules.primavtodor.errors import RecordNotFoundError, RecordValidationError
from yukiyasha.modules.primavtodor.records import Records, _num
from yukiyasha.modules.primavtodor.schema import KIND_EMPLOYEES, KIND_WAYBILLS
from yukiyasha.modules.primavtodor.sections import SECTIONS_BY_ID

CODES: tuple[tuple[str, str], ...] = (
    ("Я", "Явка"),
    ("В", "Выходной"),
    ("РВ", "Работа в выходной или праздничный день"),
    ("ОТ", "Отпуск"),
    ("Б", "Больничный"),
    ("К", "Командировка"),
    ("ПР", "Прогул"),
)
CODE_VALUES = {code for code, _ in CODES}
AUTO_CODE = "Я"
OFF_DAY_CODE = "РВ"  # a waybill on a weekend or a holiday
WORKED_CODES = {AUTO_CODE, OFF_DAY_CODE}


class Timesheet:
    def __init__(self, disk: DiskModule, records: Records) -> None:
        self._disk = disk
        self._records = records
        self._dir = SECTIONS_BY_ID["timesheet"].path

    def codes(self) -> list[dict[str, str]]:
        return [{"code": code, "label": label} for code, label in CODES]

    # ----- helpers -----

    @staticmethod
    def _parse_month(month: str) -> tuple[int, int]:
        try:
            year_text, month_text = month.split("-")
            year, number = int(year_text), int(month_text)
            if len(year_text) == 4 and len(month_text) == 2 and 2000 <= year <= 2100:
                if 1 <= number <= 12:
                    return year, number
        except ValueError:
            pass
        raise RecordValidationError({"month": "Укажите месяц в формате ГГГГ-ММ"})

    def _marks_path(self, month: str) -> str:
        return f"{self._dir}/{month}.json"

    def _load_marks(self, month: str) -> dict[str, dict[str, str]]:
        try:
            data = json.loads(self._disk.read_text(self._marks_path(month)))
        except (FileNotFoundError, ValueError, DiskError):
            return {}
        raw = data.get("marks") if isinstance(data, dict) else None
        if not isinstance(raw, dict):
            return {}
        marks: dict[str, dict[str, str]] = {}
        for employee_id, days in raw.items():
            if isinstance(days, dict):
                clean = {
                    str(day): str(code)
                    for day, code in days.items()
                    if str(code) in CODE_VALUES
                }
                if clean:
                    marks[str(employee_id)] = clean
        return marks

    # ----- public API -----

    def month_view(self, month: str) -> dict[str, object]:
        year, number = self._parse_month(month)
        days_in_month = calendar.monthrange(year, number)[1]
        prefix = f"{month}-"

        waybill_days: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        distance: dict[str, int] = defaultdict(int)
        for waybill in self._records.snapshot(KIND_WAYBILLS):
            day = str(waybill.get("date", ""))
            if not day.startswith(prefix):
                continue
            driver = str(waybill.get("driver_id", ""))
            waybill_days[driver][day] += 1
            start, end = _num(waybill.get("odometer_out")), _num(waybill.get("odometer_in"))
            if start is not None and end is not None and end >= start:
                distance[driver] += int(end - start)

        marks = self._load_marks(month)
        days = []
        for number_in_month in range(1, days_in_month + 1):
            moment = date(year, number, number_in_month)
            kind = calendar_ru.day_kind(moment)
            days.append(
                {
                    "day": number_in_month,
                    "date": f"{prefix}{number_in_month:02d}",
                    "weekday": moment.weekday(),
                    "weekend": moment.weekday() >= 5,
                    "kind": kind,  # work | off | short, from the production calendar
                    "off": kind == calendar_ru.OFF,
                    "hours": calendar_ru.working_hours(moment),
                }
            )

        employees = [
            employee
            for employee in self._records.snapshot(KIND_EMPLOYEES)
            if employee.get("active", True)
            or str(employee["id"]) in waybill_days
            or str(employee["id"]) in marks
        ]
        employees.sort(key=lambda e: str(e.get("full_name", "")).casefold())

        rows = []
        for employee in employees:
            employee_id = str(employee["id"])
            cells = []
            by_code: dict[str, int] = defaultdict(int)
            waybill_total = 0
            for day in days:
                iso = str(day["date"])
                auto = waybill_days[employee_id].get(iso, 0) if employee_id in waybill_days else 0
                manual = marks.get(employee_id, {}).get(iso)
                if manual:
                    code, source = manual, "manual"
                elif auto:
                    code = OFF_DAY_CODE if day["off"] else AUTO_CODE
                    source = "waybill"
                else:
                    code, source = "", None
                if code:
                    by_code[code] += 1
                waybill_total += auto
                cells.append(
                    {
                        "date": iso,
                        "code": code,
                        "source": source,
                        "waybills": auto,
                        "conflict": bool(manual and auto and manual not in WORKED_CODES),
                    }
                )
            rows.append(
                {
                    "employee_id": employee_id,
                    "name": employee.get("full_name"),
                    "position": employee.get("position"),
                    "personnel_number": employee.get("personnel_number"),
                    "active": bool(employee.get("active", True)),
                    "cells": cells,
                    "totals": {
                        "worked": by_code.get(AUTO_CODE, 0) + by_code.get(OFF_DAY_CODE, 0),
                        "off_day_work": by_code.get(OFF_DAY_CODE, 0),
                        "waybills": waybill_total,
                        "distance": distance.get(employee_id, 0),
                        "by_code": dict(by_code),
                    },
                }
            )

        return {
            "month": month,
            "days": days,
            "codes": self.codes(),
            "norm": calendar_ru.month_norm(year, number),
            "rows": rows,
        }

    def set_mark(
        self, month: str, employee_id: str, day: str, code: str | None
    ) -> dict[str, object]:
        """Set (or, with ``code`` empty, clear) the manual mark of one employee on one day."""
        year, number = self._parse_month(month)
        try:
            parsed = date.fromisoformat(day)
        except ValueError as exc:
            raise RecordValidationError({"date": "Укажите дату в формате ГГГГ-ММ-ДД"}) from exc
        if (parsed.year, parsed.month) != (year, number):
            raise RecordValidationError({"date": "Дата не относится к выбранному месяцу"})
        code = (code or "").strip() or None
        if code is not None and code not in CODE_VALUES:
            raise RecordValidationError({"code": "Выберите отметку из списка"})
        known = {str(e["id"]) for e in self._records.snapshot(KIND_EMPLOYEES)}
        if employee_id not in known:
            raise RecordNotFoundError(employee_id)

        marks = self._load_marks(month)
        days = marks.setdefault(employee_id, {})
        if code is None:
            days.pop(day, None)
        else:
            days[day] = code
        if not days:
            marks.pop(employee_id, None)

        text = json.dumps({"month": month, "marks": marks}, ensure_ascii=False, indent=2) + "\n"
        self._disk.write_text(self._marks_path(month), text, overwrite=True)
        return {"employee_id": employee_id, "date": day, "code": code}

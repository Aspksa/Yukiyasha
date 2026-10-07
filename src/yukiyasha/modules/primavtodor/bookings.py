"""График машин: who has which car on which days.

A booking is a car, a driver and a range of days, either a business trip or a day fully taken
(or a car out of service). Records are JSON files ``book-xxxxxxxx.json`` in the garage folder.
Overlaps are shown, never forbidden: the owner decides.
"""

from datetime import date, timedelta

from yukiyasha.modules.disk import DiskModule
from yukiyasha.modules.primavtodor import calendar_ru
from yukiyasha.modules.primavtodor.errors import RecordValidationError
from yukiyasha.modules.primavtodor.records import (
    Records,
    RecordStore,
    _now,
    format_date,
    vehicle_at,
)
from yukiyasha.modules.primavtodor.schema import (
    KIND_EMPLOYEES,
    KIND_VEHICLES,
    Entity,
)

KIND_BOOKINGS = "bookings"
BOOKING_KINDS = (
    ("trip", "Командировка"),
    ("busy", "Занята на целый день"),
    ("service", "Ремонт / ТО"),
)
_KIND_LABELS = dict(BOOKING_KINDS)
MAX_WINDOW_DAYS = 62
MAX_NOTE = 200

_ENTITY = Entity(
    kind=KIND_BOOKINGS,
    section_id="garage",
    id_prefix="book",
    title="График машин",
    singular="занятость",
    new_label="Записать",
    fields=(),
    columns=(),
)


def _day(raw: object, name: str, errors: dict[str, str]) -> date | None:
    if raw in (None, ""):
        errors[name] = "Обязательное поле"
        return None
    try:
        return date.fromisoformat(str(raw))
    except ValueError:
        errors[name] = "Дата в формате ГГГГ-ММ-ДД"
        return None


class Bookings:
    def __init__(self, disk: DiskModule, data: Records) -> None:
        self._store = RecordStore(disk, _ENTITY)
        self._data = data

    # ----- storage -----

    def _all(self) -> list[dict[str, object]]:
        return self._store.load_all()[0]

    def _clean(self, payload: dict[str, object]) -> dict[str, object]:
        errors: dict[str, str] = {}
        vehicles = {str(r["id"]): r for r in self._data.snapshot(KIND_VEHICLES)}
        drivers = {
            str(r["id"]): r for r in self._data.snapshot(KIND_EMPLOYEES) if r.get("is_driver")
        }
        kind = str(payload.get("kind") or "trip")
        if kind not in _KIND_LABELS:
            errors["kind"] = "Выберите из списка"
        vehicle_id = str(payload.get("vehicle_id") or "")
        if vehicle_id not in vehicles:
            errors["vehicle_id"] = "Выберите машину"
        driver_id = str(payload.get("driver_id") or "")
        if driver_id and driver_id not in drivers:
            errors["driver_id"] = "Выберите водителя из списка"
        if not driver_id and kind != "service":
            errors["driver_id"] = "Выберите водителя"
        start = _day(payload.get("date_from"), "date_from", errors)
        end = _day(payload.get("date_to") or payload.get("date_from"), "date_to", errors)
        if start and end and end < start:
            errors["date_to"] = "Не раньше даты начала"
        if start and end and (end - start).days > 366:
            errors["date_to"] = "Не больше года"
        note = str(payload.get("note") or "").strip()
        if len(note) > MAX_NOTE:
            errors["note"] = f"Не больше {MAX_NOTE} символов"
        if errors:
            raise RecordValidationError(errors)
        assert start and end
        return {
            "vehicle_id": vehicle_id,
            "driver_id": driver_id or None,
            "date_from": start.isoformat(),
            "date_to": end.isoformat(),
            "kind": kind,
            "note": note,
        }

    def create(self, payload: dict[str, object]) -> dict[str, object]:
        values = self._clean(payload)
        now = _now()
        record = {"id": self._store.new_id(), "created_at": now, "updated_at": now, **values}
        self._store.save(record, overwrite=False)
        return self._view(record, self._all())

    def update(self, record_id: str, payload: dict[str, object]) -> dict[str, object]:
        existing = self._store.load(record_id)
        record = {
            "id": record_id,
            "created_at": existing.get("created_at") or _now(),
            "updated_at": _now(),
            **self._clean(payload),
        }
        self._store.save(record, overwrite=True)
        return self._view(record, self._all())

    def delete(self, record_id: str) -> None:
        self._store.delete(record_id)

    # ----- views -----

    @staticmethod
    def _overlap(a: dict[str, object], b: dict[str, object]) -> bool:
        return str(a["date_from"]) <= str(b["date_to"]) and str(b["date_from"]) <= str(a["date_to"])

    def _conflicts(
        self, record: dict[str, object], everything: list[dict[str, object]]
    ) -> list[str]:
        found: list[str] = []
        for other in everything:
            if other["id"] == record["id"] or not self._overlap(record, other):
                continue
            if other["vehicle_id"] == record["vehicle_id"]:
                found.append(f"Машина уже занята {self._span(other)}")
            elif record.get("driver_id") and other.get("driver_id") == record["driver_id"]:
                found.append(f"Водитель уже в другой записи {self._span(other)}")
        return found

    @staticmethod
    def _span(record: dict[str, object]) -> str:
        start, end = str(record["date_from"]), str(record["date_to"])
        if start == end:
            return format_date(start)
        return f"{format_date(start)} – {format_date(end)}"

    def _view(
        self, record: dict[str, object], everything: list[dict[str, object]]
    ) -> dict[str, object]:
        drivers = {str(r["id"]): r for r in self._data.snapshot(KIND_EMPLOYEES)}
        vehicles = {str(r["id"]): r for r in self._data.snapshot(KIND_VEHICLES)}
        return self._row(record, everything, drivers, vehicles)

    def _row(
        self,
        record: dict[str, object],
        everything: list[dict[str, object]],
        drivers: dict[str, dict[str, object]],
        vehicles: dict[str, dict[str, object]],
    ) -> dict[str, object]:
        driver = drivers.get(str(record.get("driver_id") or ""))
        vehicle = vehicles.get(str(record["vehicle_id"]))
        start, end = date.fromisoformat(str(record["date_from"])), date.fromisoformat(
            str(record["date_to"])
        )
        return {
            "id": record["id"],
            "vehicle_id": record["vehicle_id"],
            "driver_id": record.get("driver_id"),
            "date_from": record["date_from"],
            "date_to": record["date_to"],
            "kind": record["kind"],
            "kind_label": _KIND_LABELS.get(str(record["kind"]), ""),
            "note": record.get("note", ""),
            "driver": str(driver["full_name"]) if driver else "",
            "vehicle": str(vehicle["plate"]) if vehicle else "— удалена —",
            "days": (end - start).days + 1,
            "span": self._span(record),
            "conflicts": self._conflicts(record, everything),
        }

    def overview(
        self, start: date, days: int, today: date, day: date | None = None
    ) -> dict[str, object]:
        """The grid cars × days, who is away now and who is free on ``day`` (default today)."""
        days = max(1, min(days, MAX_WINDOW_DAYS))
        last = start + timedelta(days=days - 1)
        everything = self._all()
        drivers = {str(r["id"]): r for r in self._data.snapshot(KIND_EMPLOYEES)}
        vehicles = {str(r["id"]): r for r in self._data.snapshot(KIND_VEHICLES)}
        rows = [self._row(r, everything, drivers, vehicles) for r in everything]
        rows.sort(key=lambda r: (str(r["date_from"]), str(r["id"])))

        def reaches(row: dict[str, object], first: date, final: date) -> bool:
            return (
                str(row["date_from"]) <= final.isoformat()
                and str(row["date_to"]) >= first.isoformat()
            )

        cars = sorted(
            (v for v in vehicles.values() if v.get("active", True)),
            key=lambda v: str(v.get("plate", "")).casefold(),
        )
        window = [r for r in rows if reaches(r, start, last)]
        listed = {str(v["id"]) for v in cars}
        in_window = {str(r["vehicle_id"]) for r in window} - listed
        cars += [vehicles[i] for i in sorted(in_window) if i in vehicles]
        away = [r for r in rows if reaches(r, today, today)]
        soon = [
            r
            for r in rows
            if today < date.fromisoformat(str(r["date_from"])) <= today + timedelta(days=7)
        ]
        return {
            "free": self._free_on(day or today, rows, cars, drivers),
            "start": start.isoformat(),
            "end": last.isoformat(),
            "today": today.isoformat(),
            "days": [
                {
                    "date": (start + timedelta(days=n)).isoformat(),
                    "kind": calendar_ru.day_kind(start + timedelta(days=n)),
                }
                for n in range(days)
            ],
            "vehicles": [
                {
                    "id": v["id"],
                    "plate": v.get("plate", ""),
                    "model": v.get("model", ""),
                    "fuel_type": v.get("fuel_type", ""),
                    "driver": self._regular_driver(v, drivers, today),
                }
                for v in cars
            ],
            "bookings": window,
            "now": away,
            "soon": soon,
            "kinds": [{"value": k, "label": label} for k, label in BOOKING_KINDS],
        }

    def _free_on(
        self,
        day: date,
        rows: list[dict[str, object]],
        cars: list[dict[str, object]],
        drivers: dict[str, dict[str, object]],
    ) -> dict[str, object]:
        """Cars and drivers with nothing booked on ``day`` and the next day they are taken."""
        iso = day.isoformat()

        def verdict(key: str, ident: object) -> tuple[bool, str | None]:
            mine = [r for r in rows if r.get(key) == ident]
            if any(str(r["date_from"]) <= iso <= str(r["date_to"]) for r in mine):
                return False, None
            later = sorted(str(r["date_from"]) for r in mine if str(r["date_from"]) > iso)
            return True, later[0] if later else None

        free_cars, free_drivers = [], []
        for car in cars:
            ok, until = verdict("vehicle_id", car["id"])
            if ok:
                free_cars.append(
                    {
                        "id": car["id"],
                        "plate": car.get("plate", ""),
                        "model": car.get("model", ""),
                        "next": until,
                        "driver": self._regular_driver(car, drivers, day),
                    }
                )
        people = sorted(drivers.values(), key=lambda p: str(p.get("full_name", "")).casefold())
        for person in people:
            if not person.get("is_driver") or not person.get("active", True):
                continue
            ok, until = verdict("driver_id", person["id"])
            if ok:
                current = vehicle_at(person, iso) or person.get("vehicle_id")
                car = next((c for c in cars if c["id"] == current), None)
                free_drivers.append(
                    {"id": person["id"], "name": str(person["full_name"]), "next": until,
                     "vehicle_id": current, "plate": car.get("plate", "") if car else ""}
                )
        return {
            "day": iso,
            "vehicles": free_cars,
            "drivers": free_drivers,
            "vehicles_total": len(cars),
            "drivers_total": sum(
                1 for p in drivers.values() if p.get("is_driver") and p.get("active", True)
            ),
        }

    @staticmethod
    def _regular_driver(
        vehicle: dict[str, object], drivers: dict[str, dict[str, object]], today: date
    ) -> str:
        for employee in drivers.values():
            current = vehicle_at(employee, today.isoformat()) or employee.get("vehicle_id")
            if employee.get("is_driver") and current == vehicle["id"]:
                return str(employee["full_name"])
        return ""

    def free(self, start: date, end: date) -> list[dict[str, object]]:
        """Cars with nothing booked in the range."""
        if end < start:
            raise RecordValidationError({"date_to": "Не раньше даты начала"})
        busy = {
            str(r["vehicle_id"])
            for r in self._all()
            if str(r["date_from"]) <= end.isoformat() and str(r["date_to"]) >= start.isoformat()
        }
        return [
            {"id": v["id"], "plate": v.get("plate", ""), "model": v.get("model", "")}
            for v in self._data.snapshot(KIND_VEHICLES)
            if v.get("active", True) and v["id"] not in busy
        ]

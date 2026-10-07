"""Load a fuel-card statement into the ГСМ section.

The card belongs to a driver, so every operation is matched card -> employee (driver) and then
to a car:

1. the driver's waybill on the date of the fill-up (the fill-up is linked to it);
2. otherwise the car of that driver's waybills of the day if they all use one car;
3. otherwise the car assigned to the driver, or the only car in the driver's waybills of the
   month.

A fill-up without a waybill still belongs to the car for the month's calculations. An operation
whose driver or car cannot be told is reported with the reason and never guessed. Re-loading the
same statement creates nothing twice. ``apply=False`` only reports what would happen.
"""

from yukiyasha.modules.primavtodor.errors import RecordValidationError
from yukiyasha.modules.primavtodor.records import Records, format_date
from yukiyasha.modules.primavtodor.schema import (
    KIND_EMPLOYEES,
    KIND_FUEL,
    KIND_VEHICLES,
    KIND_WAYBILLS,
)
from yukiyasha.modules.primavtodor.statement import FuelOperation, parse_statement


def _key(card: object, day: object, liters: object) -> tuple[str, str, float]:
    try:
        amount = round(float(str(liters)), 3)
    except ValueError:
        amount = 0.0
    return str(card), str(day), amount


def import_statement(
    data: Records, content: bytes, filename: str, *, apply: bool
) -> dict[str, object]:
    operations, period = parse_statement(content, filename)

    employees = data.snapshot(KIND_EMPLOYEES)
    drivers_by_id = {e["id"]: e for e in employees}
    drivers = {str(e.get("fuel_card_number")): e for e in employees if e.get("fuel_card_number")}
    waybills_by_driver_day: dict[tuple[str, str], list[dict[str, object]]] = {}
    for waybill in data.snapshot(KIND_WAYBILLS):
        index = (str(waybill.get("driver_id")), str(waybill.get("date")))
        waybills_by_driver_day.setdefault(index, []).append(waybill)
    vehicles = {str(v["id"]): v for v in data.snapshot(KIND_VEHICLES)}

    # The card is the driver's current one (the card stored on an old fill-up may be outdated).
    card_of_waybill = {
        w["id"]: str(drivers_by_id.get(w.get("driver_id"), {}).get("fuel_card_number") or "")
        for w in data.snapshot(KIND_WAYBILLS)
    }
    month_waybills: dict[str, set[str]] = {}  # driver -> cars of the driver's waybills, by month
    for w in data.snapshot(KIND_WAYBILLS):
        key = f"{w.get('driver_id')}|{str(w.get('date'))[:7]}"
        month_waybills.setdefault(key, set()).add(str(w.get("vehicle_id")))
    # (card, date, litres) -> times already on file ("" for a record entered by hand)
    known: dict[tuple[str, str, float], list[str]] = {}
    for fuel in data.snapshot(KIND_FUEL):
        owner = drivers_by_id.get(fuel.get("driver_id"), {})
        card = (
            card_of_waybill.get(fuel.get("waybill_id"))
            or str(owner.get("fuel_card_number") or "")
            or fuel.get("card_number")
        )
        key = _key(card, fuel.get("date"), fuel.get("liters"))
        known.setdefault(key, []).append(str(fuel.get("time") or ""))

    report: list[dict[str, object]] = []
    counts = {"new": 0, "duplicate": 0, "unmatched": 0, "failed": 0}
    liters_new = 0.0
    for op in operations:
        entry, payload = _classify(
            op, drivers, waybills_by_driver_day, month_waybills, vehicles, known
        )
        if payload is not None and apply:
            try:
                record = data.create(KIND_FUEL, payload)
                entry["id"] = record["id"]
            except RecordValidationError as exc:
                entry["status"] = "failed"
                entry["reason"] = "; ".join(exc.fields.values()) or exc.message
        if entry["status"] == "new":
            liters_new += op.liters
            known.setdefault(_key(op.card, op.day.isoformat(), op.liters), []).append(op.time)
        counts[str(entry["status"])] += 1
        report.append(entry)

    return {
        "filename": filename,
        "period": period,
        "applied": apply,
        "counts": {"total": len(report), **counts},
        "liters_new": round(liters_new, 3),
        "operations": report,
    }


def _classify(
    op: FuelOperation,
    drivers: dict[str, dict[str, object]],
    waybills: dict[tuple[str, str], list[dict[str, object]]],
    month_waybills: dict[str, set[str]],
    vehicles: dict[str, dict[str, object]],
    known: dict[tuple[str, str, float], list[str]],
) -> tuple[dict[str, object], dict[str, object] | None]:
    day = op.day.isoformat()
    entry: dict[str, object] = {
        "row": op.row, "card": op.card, "date": day, "time": op.time, "station": op.station,
        "fuel_type": op.fuel_type, "liters": op.liters, "price": op.price, "amount": op.amount,
        "status": "unmatched", "reason": "", "driver": "", "waybill": "", "vehicle": "",
    }  # fmt: skip

    times = known.get(_key(op.card, day, op.liters), [])
    # A record with the same time matches; a hand-entered one without a time stands for exactly
    # one fill-up, so a second real fill-up of the same size on that day is still loaded.
    match = op.time if op.time in times else ("" if "" in times else None)
    if match is not None:
        times.remove(match)
        entry["status"] = "duplicate"
        entry["reason"] = "Такая заправка уже есть"
        return entry, None

    driver = drivers.get(op.card)
    if driver is None:
        entry["reason"] = f"Карта {op.card} не закреплена ни за одним сотрудником"
        return entry, None
    entry["driver"] = str(driver.get("full_name") or "")

    payload: dict[str, object] = {
        "date": day,
        "time": op.time[:8],
        "liters": op.liters,
        "price_per_liter": op.price,
        "fuel_type": op.fuel_type or None,
        "station": op.station[:120],
    }
    same_day = waybills.get((str(driver["id"]), day), [])
    vehicle_id: str | None = None
    if len(same_day) == 1:
        waybill = same_day[0]
        payload["waybill_id"] = waybill["id"]
        entry["waybill"] = str(waybill.get("number") or "")
        vehicle_id = str(waybill.get("vehicle_id"))
    else:
        cars = {str(w.get("vehicle_id")) for w in same_day}
        if len(cars) == 1:
            vehicle_id = cars.pop()
        elif len(cars) > 1:
            numbers = ", ".join(str(w.get("number")) for w in same_day)
            entry["reason"] = (
                f"За {format_date(day)} листы № {numbers} на разных машинах: непонятно, "
                "на какую машину заправка"
            )
            return entry, None
        else:
            vehicle_id = str(driver.get("vehicle_id") or "") or None
            if vehicle_id is None:
                month_cars = month_waybills.get(f"{driver['id']}|{day[:7]}", set())
                if len(month_cars) == 1:
                    vehicle_id = next(iter(month_cars))
        if vehicle_id is None:
            entry["reason"] = (
                f"У водителя «{entry['driver']}» нет машины: закрепите её или заведите "
                f"путевой лист за {format_date(day)}"
            )
            return entry, None
        payload["driver_id"] = driver["id"]
        payload["vehicle_id"] = vehicle_id
    entry["status"] = "new"
    entry["vehicle"] = str(vehicles.get(vehicle_id, {}).get("plate") or "")
    return entry, payload

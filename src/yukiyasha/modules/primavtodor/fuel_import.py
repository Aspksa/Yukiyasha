"""Load a fuel-card statement into the ГСМ section.

Every operation is matched through the chain the module is built on: card number -> employee
(driver) -> the waybill of that driver on the date of the fill-up. An operation that cannot be
matched unambiguously is reported with the reason and never guessed. Re-loading the same
statement creates nothing twice. ``apply=False`` only reports what would happen.
"""

from yukiyasha.modules.primavtodor.errors import RecordValidationError
from yukiyasha.modules.primavtodor.records import Records, format_date
from yukiyasha.modules.primavtodor.schema import KIND_EMPLOYEES, KIND_FUEL, KIND_WAYBILLS
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

    drivers = {
        str(e.get("fuel_card_number")): e
        for e in data.snapshot(KIND_EMPLOYEES)
        if e.get("fuel_card_number")
    }
    waybills_by_driver_day: dict[tuple[str, str], list[dict[str, object]]] = {}
    for waybill in data.snapshot(KIND_WAYBILLS):
        index = (str(waybill.get("driver_id")), str(waybill.get("date")))
        waybills_by_driver_day.setdefault(index, []).append(waybill)

    # (card, date, litres) -> times already on file ("" for a record entered by hand)
    known: dict[tuple[str, str, float], set[str]] = {}
    for fuel in data.snapshot(KIND_FUEL):
        key = _key(fuel.get("card_number"), fuel.get("date"), fuel.get("liters"))
        known.setdefault(key, set()).add(str(fuel.get("time") or ""))

    report: list[dict[str, object]] = []
    counts = {"new": 0, "duplicate": 0, "unmatched": 0, "failed": 0}
    liters_new = 0.0
    for op in operations:
        entry, payload = _classify(op, drivers, waybills_by_driver_day, known)
        if payload is not None and apply:
            try:
                record = data.create(KIND_FUEL, payload)
                entry["id"] = record["id"]
            except RecordValidationError as exc:
                entry["status"] = "failed"
                entry["reason"] = "; ".join(exc.fields.values()) or exc.message
        if entry["status"] == "new":
            liters_new += op.liters
            known.setdefault(_key(op.card, op.day.isoformat(), op.liters), set()).add(op.time)
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
    known: dict[tuple[str, str, float], set[str]],
) -> tuple[dict[str, object], dict[str, object] | None]:
    day = op.day.isoformat()
    entry: dict[str, object] = {
        "row": op.row, "card": op.card, "date": day, "time": op.time, "station": op.station,
        "fuel_type": op.fuel_type, "liters": op.liters, "price": op.price, "amount": op.amount,
        "status": "unmatched", "reason": "", "driver": "", "waybill": "",
    }  # fmt: skip

    times = known.get(_key(op.card, day, op.liters), set())
    if op.time in times or "" in times:
        entry["status"] = "duplicate"
        entry["reason"] = "Такая заправка уже есть"
        return entry, None

    driver = drivers.get(op.card)
    if driver is None:
        entry["reason"] = f"Карта {op.card} не закреплена ни за одним сотрудником"
        return entry, None
    entry["driver"] = str(driver.get("full_name") or "")

    candidates = waybills.get((str(driver["id"]), day), [])
    if not candidates:
        entry["reason"] = f"Нет путевого листа за {format_date(day)} у водителя «{entry['driver']}»"
        return entry, None
    if len(candidates) > 1:
        numbers = ", ".join(str(w.get("number")) for w in candidates)
        entry["reason"] = f"Несколько путевых листов за {format_date(day)} (№ {numbers})"
        return entry, None
    waybill = candidates[0]
    entry["status"] = "new"
    entry["waybill"] = str(waybill.get("number") or "")
    payload: dict[str, object] = {
        "waybill_id": waybill["id"],
        "date": day,
        "time": op.time[:8],
        "liters": op.liters,
        "price_per_liter": op.price,
        "fuel_type": op.fuel_type or None,
        "station": op.station[:120],
    }
    return entry, payload

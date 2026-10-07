"""Month calculations per vehicle: balances, mileage, actual consumption and the norm.

For every vehicle with waybills in the month:

* **fuel at the start** is the remainder at departure on the first waybill (first day);
* **fuel at the end** is the remainder at return on the last closed waybill;
* **mileage by waybills** is the sum of the closed waybills' distances; **by the odometer** it is
  the last closed waybill's return reading minus the first waybill's departure reading, so the
  difference is the mileage nobody wrote a waybill for;
* **actual consumption** = start + fill-ups - end;
* **by the norm** = the sum of each waybill's norm (its own season's rate x its distance);
* **deviation** = actual - norm (plus means an overrun).

The same figures are summed per driver. Nothing here is stored: it is derived on every read.
"""

from yukiyasha.modules.primavtodor.records import Records
from yukiyasha.modules.primavtodor.schema import (
    KIND_EMPLOYEES,
    KIND_FUEL,
    KIND_VEHICLES,
    KIND_WAYBILLS,
)

ROUND = 3


def _num(value: object) -> float | None:
    try:
        return None if value in (None, "") else float(str(value))
    except ValueError:
        return None


def _r(value: float | None) -> float | None:
    return None if value is None else round(value, ROUND)


def _sorted(waybills: list[dict[str, object]]) -> list[dict[str, object]]:
    return sorted(waybills, key=lambda w: (str(w.get("date")), str(w.get("number"))))


def _totals(rows: list[dict[str, object]], views: dict[str, dict[str, object]]) -> dict[str, float]:
    """Distance, actual consumption and norm over the *closed* waybills among ``rows``."""
    distance = consumption = norm = 0.0
    for waybill in rows:
        computed = views.get(str(waybill["id"]), {})
        if computed.get("distance") is None:
            continue
        distance += float(computed["distance"])
        consumption += float(computed.get("consumption") or 0)
        norm += float(computed.get("norm") or 0)
    return {"distance": distance, "consumption": consumption, "norm": norm}


def vehicle_calculations(data: Records, month: str) -> dict[str, object]:
    views = {str(r["id"]): r["computed"] for r in data.list_records(KIND_WAYBILLS)["records"]}
    waybills = [
        w for w in data.snapshot(KIND_WAYBILLS) if str(w.get("date", "")).startswith(month)
    ]
    fuel = data.snapshot(KIND_FUEL)
    vehicles = {str(v["id"]): v for v in data.snapshot(KIND_VEHICLES)}
    names = {str(e["id"]): str(e.get("full_name") or "") for e in data.snapshot(KIND_EMPLOYEES)}

    by_vehicle: dict[str, list[dict[str, object]]] = {}
    for waybill in _sorted(waybills):
        by_vehicle.setdefault(str(waybill.get("vehicle_id")), []).append(waybill)

    result = []
    for vehicle_id, rows in by_vehicle.items():
        vehicle = vehicles.get(vehicle_id, {})
        closed = [w for w in rows if views.get(str(w["id"]), {}).get("distance") is not None]
        first, last_closed = rows[0], (closed[-1] if closed else None)
        ids = {str(w["id"]) for w in rows}
        fills = sum(float(f.get("liters") or 0) for f in fuel if str(f.get("waybill_id")) in ids)

        fuel_start = _num(first.get("fuel_out")) or 0.0
        fuel_end = _num(last_closed.get("fuel_in")) if last_closed else None
        odometer_start = _num(first.get("odometer_out"))
        odometer_end = _num(last_closed.get("odometer_in")) if last_closed else None
        totals = _totals(closed, views)

        km_odometer = (
            odometer_end - odometer_start
            if odometer_start is not None and odometer_end is not None
            else None
        )
        actual = fuel_start + fills - fuel_end if fuel_end is not None else None
        deviation = actual - totals["norm"] if actual is not None and totals["norm"] else None
        seasons = {str(w.get("season") or "") for w in closed}
        rates = {
            _num(vehicle.get("norm_winter" if s == "winter" else "norm_summer")) for s in seasons
        }
        rate = rates.pop() if len(rates) == 1 else None

        notes = []
        open_count = len(rows) - len(closed)
        if open_count:
            notes.append(f"Открытых листов: {open_count}, в расчёт идут только закрытые")
        if km_odometer is not None and abs(km_odometer - totals["distance"]) > 0.5:
            notes.append(
                f"По одометру {km_odometer:g} км, по листам {totals['distance']:g} км: "
                f"{km_odometer - totals['distance']:g} км без путевых листов"
            )
        if actual is not None and abs(actual - totals["consumption"]) > 0.5:
            notes.append(
                f"Расход по остаткам {actual:g} л, по листам {totals['consumption']:g} л: "
                "остатки между листами не сходятся"
            )
        if closed and not totals["norm"]:
            notes.append("Нормы расхода нет: сравнить не с чем")

        per_driver = []
        for driver_id in dict.fromkeys(str(w.get("driver_id")) for w in rows):
            own = [w for w in rows if str(w.get("driver_id")) == driver_id]
            own_closed = [w for w in own if views.get(str(w["id"]), {}).get("distance") is not None]
            sums = _totals(own_closed, views)
            own_deviation = sums["consumption"] - sums["norm"] if sums["norm"] else None
            per_driver.append(
                {
                    "driver_id": driver_id,
                    "driver": names.get(driver_id, "?"),
                    "waybills": len(own),
                    "closed": len(own_closed),
                    "km": _r(sums["distance"]),
                    "consumption": _r(sums["consumption"]),
                    "norm": _r(sums["norm"]),
                    "deviation": _r(own_deviation),
                }
            )

        result.append(
            {
                "vehicle_id": vehicle_id,
                "plate": str(vehicle.get("plate") or "?"),
                "model": str(vehicle.get("model") or ""),
                "fuel_type": str(vehicle.get("fuel_type") or ""),
                "waybills": len(rows),
                "closed": len(closed),
                "first": {"number": first.get("number"), "date": first.get("date")},
                "last": (
                    {"number": last_closed.get("number"), "date": last_closed.get("date")}
                    if last_closed
                    else None
                ),
                "odometer_start": _r(odometer_start),
                "odometer_end": _r(odometer_end),
                "km_odometer": _r(km_odometer),
                "km_waybills": _r(totals["distance"]),
                "fuel_start": _r(fuel_start),
                "fills": _r(fills),
                "fuel_end": _r(fuel_end),
                "consumption": _r(actual),
                "consumption_waybills": _r(totals["consumption"]),
                "norm": _r(totals["norm"]),
                "norm_rate": rate,
                "deviation": _r(deviation),
                "deviation_pct": (
                    round(deviation / totals["norm"] * 100, 1) if deviation is not None else None
                ),
                "drivers": per_driver,
                "notes": notes,
            }
        )

    result.sort(key=lambda v: str(v["plate"]))
    sums_all = {
        key: _r(sum(float(v[key] or 0) for v in result))
        for key in ("km_waybills", "fuel_start", "fills", "fuel_end", "consumption", "norm")
    }
    sums_all["deviation"] = _r(
        sum(float(v["deviation"]) for v in result if v["deviation"] is not None)
    )
    return {"month": month, "vehicles": result, "totals": sums_all}

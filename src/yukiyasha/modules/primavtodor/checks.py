"""Control of fuel use and waybills for a month: finds what does not add up.

Pure rules over the records, no I/O of their own. Every finding names the rule (``code``), says
what is wrong in plain Russian and points at the record. A finding is advice: people decide.
Severity: ``error`` (impossible or contradicting data), ``warn`` (needs a look), ``info``.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median

from yukiyasha.modules.primavtodor import calendar_ru

ERROR, WARN, INFO = "error", "warn", "info"
SEVERITY_ORDER = {ERROR: 0, WARN: 1, INFO: 2}

OVERRUN_WARN, OVERRUN_ERROR = 0.10, 0.25  # share of the norm
UNDERRUN = 0.60  # consumption below this share of the norm is suspicious
MIN_DISTANCE_FOR_RATIOS = 50  # km, shorter trips say nothing about consumption
ODOMETER_GAP_KM = 20
FUEL_GAP_L = 2.0
MAX_DAILY_KM = 1000
OPEN_WAYBILL_DAYS = 3
PRICE_DEVIATION = 0.25
TANK_SLACK = 1.05


@dataclass(frozen=True, slots=True)
class Finding:
    code: str
    severity: str
    title: str
    detail: str
    kind: str  # record kind the finding is about: waybills | fuel | vehicles
    record_id: str
    date: str
    subject: str  # a short label: vehicle, driver

    @property
    def id(self) -> str:
        return f"{self.code}:{self.record_id}"

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id, "code": self.code, "severity": self.severity, "title": self.title,
            "detail": self.detail, "kind": self.kind, "record_id": self.record_id,
            "date": self.date, "subject": self.subject,
        }


def _num(value: object) -> float | None:
    try:
        return None if value in (None, "") else float(str(value))
    except ValueError:
        return None


def _is_diesel(fuel_type: object) -> bool | None:
    text = str(fuel_type or "")
    if not text:
        return None
    return text == "ДТ"


def run_checks(
    *,
    month: str,
    today: date,
    waybills: list[dict[str, object]],  # every waybill, raw
    views: dict[str, dict[str, object]],  # waybill id -> computed values
    fuel: list[dict[str, object]],
    vehicles: dict[str, dict[str, object]],
    drivers: dict[str, dict[str, object]],
) -> list[Finding]:
    findings: list[Finding] = []

    def label(waybill: dict[str, object]) -> str:
        vehicle = vehicles.get(str(waybill.get("vehicle_id")), {})
        driver = drivers.get(str(waybill.get("driver_id")), {})
        return f"{vehicle.get('plate', '?')} · {driver.get('full_name', '?')}"

    def add(code, severity, title, detail, kind, record, day, subject) -> None:  # noqa: ANN001
        item = Finding(code, severity, title, detail, kind, str(record), str(day), subject)
        findings.append(item)

    by_id = {str(w["id"]): w for w in waybills}
    in_month = [w for w in waybills if str(w.get("date", "")).startswith(month)]

    # ----- continuity of one vehicle from waybill to waybill -----
    by_vehicle: dict[str, list[dict[str, object]]] = {}
    for waybill in sorted(waybills, key=lambda w: (str(w.get("date")), str(w.get("number")))):
        by_vehicle.setdefault(str(waybill.get("vehicle_id")), []).append(waybill)
    for chain in by_vehicle.values():
        for previous, current in zip(chain, chain[1:], strict=False):
            if not str(current.get("date", "")).startswith(month):
                continue
            out, back = _num(current.get("odometer_out")), _num(previous.get("odometer_in"))
            number = previous.get("number")
            if out is not None and back is not None:
                if out < back:
                    add("ODO_REWIND", ERROR, "Пробег уменьшился",
                        f"При выезде {out:g} км, а в прошлом листе № {number} при возврате "
                        f"{back:g} км", "waybills", current["id"], current["date"], label(current))
                elif out - back > ODOMETER_GAP_KM:
                    add("ODO_GAP", WARN, "Пробег между листами не записан",
                        f"Между листом № {number} и этим {out - back:g} км без путевого листа",
                        "waybills", current["id"], current["date"], label(current))
            fuel_out, fuel_back = _num(current.get("fuel_out")), _num(previous.get("fuel_in"))
            if fuel_out is not None and fuel_back is not None:
                if abs(fuel_out - fuel_back) > FUEL_GAP_L:
                    add("FUEL_GAP", WARN, "Остаток топлива не совпал",
                        f"При выезде {fuel_out:g} л, а в листе № {number} при возврате "
                        f"{fuel_back:g} л", "waybills", current["id"], current["date"],
                        label(current))

    # ----- each waybill on its own -----
    drivers_by_day: dict[tuple[str, str], list[dict[str, object]]] = {}
    for waybill in in_month:
        computed = views.get(str(waybill["id"]), {})
        day, number = str(waybill["date"]), waybill.get("number")
        distance, consumption = _num(computed.get("distance")), _num(computed.get("consumption"))
        norm, deviation = _num(computed.get("norm")), _num(computed.get("deviation"))
        drivers_by_day.setdefault((str(waybill.get("driver_id")), day), []).append(waybill)

        if consumption is not None and consumption < 0:
            add("NEG_FUEL", ERROR, "Расход меньше нуля",
                f"Лист № {number}: остаток при возврате больше, чем было топлива",
                "waybills", waybill["id"], day, label(waybill))
        if distance is not None and distance > MAX_DAILY_KM:
            add("BIG_DISTANCE", WARN, "Очень большой пробег за один лист",
                f"Лист № {number}: {distance:g} км", "waybills", waybill["id"], day, label(waybill))
        if (
            distance is not None and distance >= MIN_DISTANCE_FOR_RATIOS
            and consumption is not None and consumption >= 0
        ):
            if consumption == 0:
                add("ZERO_FUEL", WARN, "Проехал, но топливо не израсходовано",
                    f"Лист № {number}: {distance:g} км, расход 0 л",
                    "waybills", waybill["id"], day, label(waybill))
            elif norm and deviation is not None:
                share = deviation / norm
                if share > OVERRUN_ERROR:
                    add("OVERRUN", ERROR, "Большой перерасход топлива",
                        f"Лист № {number}: расход {consumption:g} л при норме {norm:g} л "
                        f"(+{share:.0%})", "waybills", waybill["id"], day, label(waybill))
                elif share > OVERRUN_WARN:
                    add("OVERRUN", WARN, "Перерасход топлива",
                        f"Лист № {number}: расход {consumption:g} л при норме {norm:g} л "
                        f"(+{share:.0%})", "waybills", waybill["id"], day, label(waybill))
                elif consumption < norm * UNDERRUN:
                    add("UNDERRUN", WARN, "Расход подозрительно мал",
                        f"Лист № {number}: расход {consumption:g} л при норме {norm:g} л",
                        "waybills", waybill["id"], day, label(waybill))
        closed = distance is not None
        if closed and not norm and distance and distance > 0:
            vehicle = vehicles.get(str(waybill.get("vehicle_id")), {})
            if not (vehicle.get("norm_summer") or vehicle.get("norm_winter")):
                add("NO_NORM", WARN, "У машины не задана норма расхода",
                    f"Лист № {number}: норму сравнить не с чем",
                    "waybills", waybill["id"], day, label(waybill))
        if not closed:
            try:
                age = (today - date.fromisoformat(day)).days
            except ValueError:
                age = 0
            if age > OPEN_WAYBILL_DAYS:
                add("OPEN_OLD", WARN, "Путевой лист не закрыт",
                    f"Лист № {number} открыт уже {age} дн.", "waybills", waybill["id"], day,
                    label(waybill))
        try:
            moment = date.fromisoformat(day)
        except ValueError:
            moment = None
        if moment and calendar_ru.day_kind(moment) == calendar_ru.OFF:
            add("OFF_DAY", INFO, "Работа в выходной или праздничный день",
                f"Лист № {number}: нужен приказ о работе в выходной",
                "waybills", waybill["id"], day, label(waybill))

    for (driver_id, day), same_day in drivers_by_day.items():
        cars = {str(w.get("vehicle_id")) for w in same_day}
        if len(cars) > 1:
            first = same_day[0]
            numbers = ", ".join(str(w.get("number")) for w in same_day)
            add("DOUBLE_DRIVER", WARN, "Водитель на двух машинах в один день",
                f"Листы № {numbers}", "waybills", first["id"], day,
                str(drivers.get(driver_id, {}).get("full_name", "?")))

    # ----- fill-ups -----
    month_fuel = [f for f in fuel if str(f.get("date", "")).startswith(month)]
    prices: dict[str, list[float]] = {}
    for record in month_fuel:
        price = _num(record.get("price_per_liter"))
        if price:
            prices.setdefault(str(record.get("fuel_type") or ""), []).append(price)
    medians = {kind: median(values) for kind, values in prices.items() if len(values) >= 5}

    seen: dict[tuple[object, ...], str] = {}
    issued: dict[str, float] = {}
    for record in month_fuel:
        waybill = by_id.get(str(record.get("waybill_id")))
        vehicle = vehicles.get(str(record.get("vehicle_id")), {})
        subject = label(waybill) if waybill else str(vehicle.get("plate", "?"))
        day, liters = str(record.get("date")), _num(record.get("liters")) or 0.0
        waybill_key = str(record.get("waybill_id"))
        issued[waybill_key] = issued.get(waybill_key, 0) + liters

        wanted, got = _is_diesel(vehicle.get("fuel_type")), _is_diesel(record.get("fuel_type"))
        if wanted is not None and got is not None and wanted != got:
            add("WRONG_FUEL", ERROR, "Заправлено не тем топливом",
                f"{liters:g} л {record.get('fuel_type')}, у машины {vehicle.get('fuel_type')}",
                "fuel", record["id"], day, subject)
        tank = _num(vehicle.get("tank_liters"))
        if tank and liters > tank:
            add("OVER_TANK", ERROR, "Заправка больше объёма бака",
                f"{liters:g} л при баке {tank:g} л", "fuel", record["id"], day, subject)
        if waybill and str(waybill.get("date")) != day:
            add("FUEL_DATE", WARN, "Дата заправки не совпадает с датой листа",
                f"Заправка {day}, лист № {waybill.get('number')} от {waybill.get('date')}",
                "fuel", record["id"], day, subject)
        key = (record.get("waybill_id"), day, record.get("time"), liters)
        if key in seen:
            add("DUP_FUEL", WARN, "Похоже на дубль заправки",
                f"{liters:g} л, {day} {record.get('time') or ''}".strip(),
                "fuel", record["id"], day, subject)
        seen.setdefault(key, str(record["id"]))
        price, typical = _num(record.get("price_per_liter")), medians.get(
            str(record.get("fuel_type") or "")
        )
        if price and typical and abs(price - typical) / typical > PRICE_DEVIATION:
            add("PRICE", INFO, "Цена заметно отличается от обычной",
                f"{price:g} ₽ за литр при типичных {typical:g} ₽",
                "fuel", record["id"], day, subject)

    cars_with_waybills = {str(w.get("vehicle_id")) for w in in_month}
    litres_without_waybills: dict[str, float] = {}
    for record in month_fuel:
        owner = str(record.get("vehicle_id") or by_id.get(str(record.get("waybill_id")), {}).get(
            "vehicle_id"
        ))
        if owner not in cars_with_waybills:
            litres_without_waybills[owner] = litres_without_waybills.get(owner, 0.0) + (
                _num(record.get("liters")) or 0.0
            )
    for owner, total in litres_without_waybills.items():
        plate = vehicles.get(owner, {}).get("plate", "?")
        add("FUEL_NO_WAYBILLS", WARN, "Заправки есть, путевых листов нет",
            f"По машине {plate} заправлено {total:g} л, а путевых листов за месяц нет",
            "vehicles", owner, f"{month}-01", str(plate))

    for waybill in in_month:
        vehicle = vehicles.get(str(waybill.get("vehicle_id")), {})
        tank = _num(vehicle.get("tank_liters"))
        have = (_num(waybill.get("fuel_out")) or 0.0) + issued.get(str(waybill["id"]), 0.0)
        if tank and have > tank * TANK_SLACK:
            add("OVER_TANK", WARN, "Остаток и заправка больше бака",
                f"Лист № {waybill.get('number')}: {have:g} л при баке {tank:g} л",
                "waybills", waybill["id"], waybill["date"], label(waybill))

    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.date, f.code, f.record_id))
    return findings


def month_end(month: str) -> date:
    first = date.fromisoformat(f"{month}-01")
    following = (first + timedelta(days=32)).replace(day=1)
    return following - timedelta(days=1)

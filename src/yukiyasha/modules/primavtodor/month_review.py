"""«Закрытие месяца»: one screen that says what is done, what does not add up and what is left."""

from datetime import date

from yukiyasha.modules.primavtodor import calendar_ru
from yukiyasha.modules.primavtodor.checks import ERROR, INFO, WARN, run_checks
from yukiyasha.modules.primavtodor.records import Records
from yukiyasha.modules.primavtodor.schema import (
    KIND_EMPLOYEES,
    KIND_FUEL,
    KIND_VEHICLES,
    KIND_WAYBILLS,
)
from yukiyasha.modules.primavtodor.settings import ModuleSettings
from yukiyasha.modules.primavtodor.timesheet import Timesheet

OK = "ok"


def _step(step_id: str, title: str, status: str, detail: str) -> dict[str, str]:
    return {"id": step_id, "title": title, "status": status, "detail": detail}


def build_review(
    data: Records,
    settings: ModuleSettings,
    timesheet: Timesheet,
    month: str,
    today: date,
    *,
    show_dismissed: bool = False,
) -> dict[str, object]:
    waybills = data.snapshot(KIND_WAYBILLS)
    fuel = data.snapshot(KIND_FUEL)
    vehicles = {str(v["id"]): v for v in data.snapshot(KIND_VEHICLES)}
    drivers = {str(e["id"]): e for e in data.snapshot(KIND_EMPLOYEES)}
    views = {str(r["id"]): r["computed"] for r in data.list_records(KIND_WAYBILLS)["records"]}

    found = run_checks(
        month=month, today=today, waybills=waybills, views=views, fuel=fuel,
        vehicles=vehicles, drivers=drivers,
    )  # fmt: skip
    dismissed = settings.dismissed()
    findings = []
    hidden = 0
    for item in found:
        entry = item.to_dict()
        note = dismissed.get(item.id)
        if note:
            hidden += 1
            if not show_dismissed:
                continue
            entry["dismissed"] = note
        findings.append(entry)
    shown = [f for f in findings if "dismissed" not in f]
    counts = {
        ERROR: sum(1 for f in shown if f["severity"] == ERROR),
        WARN: sum(1 for f in shown if f["severity"] == WARN),
        INFO: sum(1 for f in shown if f["severity"] == INFO),
        "dismissed": hidden,
    }

    in_month = [w for w in waybills if str(w.get("date", "")).startswith(month)]
    open_count = sum(1 for w in in_month if views.get(str(w["id"]), {}).get("distance") is None)
    month_fuel = [f for f in fuel if str(f.get("date", "")).startswith(month)]
    liters = round(sum(float(f.get("liters") or 0) for f in month_fuel), 3)
    sheet = timesheet.month_view(month)
    conflicts = sum(1 for row in sheet["rows"] for c in row["cells"] if c["conflict"])
    norm = calendar_ru.month_norm(int(month[:4]), int(month[5:7]))

    steps = [
        _step(
            "waybills", "Путевые листы",
            "info" if not in_month else (OK if not open_count else WARN),
            "Нет путевых листов за этот месяц" if not in_month
            else f"Листов: {len(in_month)}, закрыто {len(in_month) - open_count}"
            + (f", открыто {open_count}: закройте их" if open_count else ""),
        ),
        _step(
            "fuel", "Заправки",
            OK if month_fuel else WARN,
            f"Заправок: {len(month_fuel)}, {liters:g} л" if month_fuel
            else "Заправок нет: загрузите выписку по картам в разделе ГСМ",
        ),
        _step(
            "checks", "Контроль расхода",
            ERROR if counts[ERROR] else (WARN if counts[WARN] else OK),
            f"Ошибок: {counts[ERROR]}, к проверке: {counts[WARN]}, к сведению: {counts[INFO]}"
            + (f"; принято: {hidden}" if hidden else ""),
        ),
        _step(
            "timesheet", "Табель",
            WARN if conflicts else OK,
            f"Норма месяца: {norm['workdays']} раб. дн., {norm['hours']} ч"
            + (f"; отметок, противоречащих путевым листам: {conflicts}" if conflicts else ""),
        ),
    ]
    ready = not counts[ERROR] and not open_count and bool(in_month)
    return {
        "month": month,
        "steps": steps,
        "counts": counts,
        "findings": findings,
        "ready": ready,
    }

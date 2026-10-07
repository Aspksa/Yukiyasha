"""Production calendar of Russia for 2026 and 2027."""

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_primavtodor_records import make_driver, make_vehicle, make_waybill
from yukiyasha.config import Settings
from yukiyasha.modules.disk import DiskModule
from yukiyasha.modules.primavtodor import PrimavtodorModule
from yukiyasha.modules.primavtodor import calendar_ru as cal
from yukiyasha.web.app import create_app


def test_the_shipped_years() -> None:
    assert cal.available_years() == (2026, 2027)
    assert cal.has_calendar(2026) and not cal.has_calendar(2030)


@pytest.mark.parametrize("year", [2026, 2027])
def test_year_totals_match_the_decrees(year: int) -> None:
    view = cal.year_view(year)

    assert view is not None
    assert view["workdays"] == 247 and view["hours"] == 1972  # 40-hour week
    assert [m["month"] for m in view["months"]] == list(range(1, 13))


@pytest.mark.parametrize(
    ("day", "kind"),
    [
        (date(2026, 1, 1), "off"),      # New Year
        (date(2026, 1, 9), "off"),      # transfer of Saturday 3 January
        (date(2026, 1, 12), "work"),
        (date(2026, 3, 9), "off"),      # 8 March is a Sunday: Monday is off
        (date(2026, 4, 30), "short"),   # before 1 May
        (date(2026, 5, 11), "off"),     # transfer for 9 May (Saturday)
        (date(2026, 11, 3), "short"),
        (date(2026, 11, 4), "off"),
        (date(2026, 12, 31), "off"),    # transferred from Sunday 4 January
        (date(2026, 10, 7), "work"),
        (date(2026, 10, 10), "off"),    # an ordinary Saturday
        (date(2027, 2, 22), "off"),     # transfer for Saturday 20 February
        (date(2027, 11, 5), "off"),
    ],
)
def test_day_kinds(day: date, kind: str) -> None:
    assert cal.day_kind(day) == kind


def test_hours_and_month_norm() -> None:
    assert cal.working_hours(date(2026, 4, 30)) == 7
    assert cal.working_hours(date(2026, 4, 29)) == 8 and cal.working_hours(date(2026, 5, 1)) == 0
    october = cal.month_norm(2026, 10)
    assert october == {"workdays": 22, "short_days": 0, "days_off": 9, "hours": 176,
                       "from_calendar": True}  # fmt: skip
    april = cal.month_norm(2026, 4)  # 30 days, 8 weekends, one shortened day
    assert (april["workdays"], april["short_days"], april["hours"]) == (22, 1, 175)


def test_other_years_fall_back_to_plain_weekends() -> None:
    assert cal.day_kind(date(2030, 1, 1)) == "work"  # no data: only weekends are days off
    assert cal.day_kind(date(2030, 1, 5)) == "off"
    assert cal.month_norm(2030, 1)["from_calendar"] is False
    assert cal.year_view(2030) is None


# ----- timesheet and API -----

def test_timesheet_uses_the_calendar(tmp_path: Path) -> None:
    disk = DiskModule(tmp_path / "disk")
    disk.start()
    module = PrimavtodorModule(disk)
    module.start()
    vehicle = make_vehicle(module)
    driver = make_driver(module, vehicle["id"])
    make_waybill(module, driver, vehicle, number="1", date="2026-10-07")  # Wednesday
    make_waybill(module, driver, vehicle, number="2", date="2026-10-10", odometer_out=1)  # Sat
    make_waybill(module, driver, vehicle, number="3", date="2026-05-11", odometer_out=2)  # holiday

    october = module.timesheet.month_view("2026-10")
    may = module.timesheet.month_view("2026-05")

    codes = {c["date"]: c["code"] for c in october["rows"][0]["cells"] if c["code"]}
    assert codes == {"2026-10-07": "Я", "2026-10-10": "РВ"}
    assert october["rows"][0]["totals"]["worked"] == 2
    assert october["norm"]["workdays"] == 22 and october["norm"]["hours"] == 176
    monday = may["days"][10]  # 11 May 2026: a Monday that is a day off by the decree
    assert monday["weekday"] == 0 and monday["off"] is True and monday["weekend"] is False
    assert may["rows"][0]["cells"][10]["code"] == "РВ"
    assert [d["hours"] for d in october["days"][:3]] == [8, 8, 0]  # Thu, Fri, Sat


@pytest.fixture
def client(tmp_path: Path):
    app = create_app(Settings(disk_dir=tmp_path / "disk"))
    with TestClient(app, base_url="http://127.0.0.1:8000") as test_client:
        yield test_client


def test_calendar_api(client: TestClient) -> None:
    years = client.get("/api/primavtodor/calendar").json()
    year = client.get("/api/primavtodor/calendar/2027").json()

    assert years["years"] == [2026, 2027]
    assert year["year"] == 2027 and len(year["months"]) == 12 and year["workdays"] == 247
    january_first = year["months"][0]["days"][0]
    assert january_first["kind"] == "off" and january_first["holiday"] is True
    assert client.get("/api/primavtodor/calendar/2030").status_code == 404

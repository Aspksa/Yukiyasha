"""The morning summary: trips, leave, open waybills, the statement inbox and the month."""

from datetime import datetime
from pathlib import Path

import pytest

from tests.test_primavtodor_records import make_driver, make_vehicle, make_waybill
from yukiyasha.modules.disk import DiskModule
from yukiyasha.modules.primavtodor import PrimavtodorModule, fuel_inbox

NOW = datetime(2026, 10, 8, 8, 30)


@pytest.fixture
def module(tmp_path: Path) -> PrimavtodorModule:
    disk = DiskModule(tmp_path / "disk")
    disk.start()
    primavtodor = PrimavtodorModule(disk)
    primavtodor.start()
    return primavtodor


def test_a_quiet_day(module: PrimavtodorModule) -> None:
    result = module.briefing(NOW)
    assert result["calm"] and result["items"] == []
    assert result["greeting"] == "Доброе утро" and result["date_label"] == "четверг, 8 октября"


def test_everything_that_needs_attention_is_listed_worst_first(module: PrimavtodorModule) -> None:
    car = make_vehicle(module, plate="Х1", model="Hino")
    driver = make_driver(module, car["id"])
    make_waybill(module, driver, car, number="1", date="2026-10-05")  # never closed
    module.bookings.create(
        {"vehicle_id": car["id"], "driver_id": driver["id"], "date_from": "2026-10-08",
         "date_to": "2026-10-09", "kind": "trip"}
    )  # fmt: skip
    module.timesheet.set_mark("2026-10", driver["id"], "2026-10-08", "Б")
    (module._disk.root / fuel_inbox.inbox_dir() / "выписка.xlsx").write_bytes(b"x")

    items = {item["id"]: item for item in module.briefing(NOW)["items"]}

    assert items["open-waybills"]["severity"] == "warn"
    assert items["inbox"]["action"] == {"kind": "inbox"}
    assert items["away"]["severity"] == "info" and "Х1" in items["away"]["detail"]
    assert items["clash"]["severity"] == "warn"  # booked while sick
    assert any(key.startswith("absent-") for key in items)
    order = [item["severity"] for item in module.briefing(NOW)["items"]]
    assert order == sorted(order, key=["error", "warn", "info", "ok"].index)

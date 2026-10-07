"""График машин: trips and busy days per car, overlaps shown but never forbidden."""

from datetime import date
from pathlib import Path

import pytest

from tests.test_primavtodor_records import make_driver, make_vehicle
from yukiyasha.modules.disk import DiskModule
from yukiyasha.modules.primavtodor import PrimavtodorModule, RecordValidationError


@pytest.fixture
def module(tmp_path: Path) -> PrimavtodorModule:
    disk = DiskModule(tmp_path / "disk")
    disk.start()
    primavtodor = PrimavtodorModule(disk)
    primavtodor.start()
    return primavtodor


def book(module, vehicle, driver, start, end, kind="trip", **extra):
    return module.bookings.create(
        {
            "vehicle_id": vehicle["id"],
            "driver_id": driver["id"],
            "date_from": start,
            "date_to": end,
            "kind": kind,
            **extra,
        }
    )


def test_trip_is_saved_and_shown(module: PrimavtodorModule) -> None:
    car = make_vehicle(module, plate="Х1", model="Hino")
    driver = make_driver(module, car["id"])

    created = book(module, car, driver, "2026-10-07", "2026-10-09", note="Находка")

    assert created["days"] == 3 and created["kind_label"] == "Командировка"
    assert created["vehicle"] == "Х1" and created["conflicts"] == []
    view = module.bookings.overview(date(2026, 10, 5), 7, date(2026, 10, 8))
    assert [b["id"] for b in view["bookings"]] == [created["id"]]
    assert [b["id"] for b in view["now"]] == [created["id"]]  # away today
    assert view["vehicles"][0]["plate"] == "Х1"


def test_overlap_on_the_same_car_is_a_warning_not_an_error(module: PrimavtodorModule) -> None:
    car = make_vehicle(module, plate="Х1", model="Hino")
    first = make_driver(module, car["id"])
    book(module, car, first, "2026-10-07", "2026-10-09")

    second = book(module, car, first, "2026-10-09", "2026-10-10", kind="busy")

    assert second["conflicts"]  # saved anyway, flagged


def test_validation_errors(module: PrimavtodorModule) -> None:
    car = make_vehicle(module, plate="Х1", model="Hino")
    driver = make_driver(module, car["id"])
    with pytest.raises(RecordValidationError) as raised:
        book(module, car, driver, "2026-10-09", "2026-10-07")
    assert "date_to" in raised.value.fields
    with pytest.raises(RecordValidationError) as raised:
        module.bookings.create({"vehicle_id": "veh-00000000", "date_from": "2026-10-07"})
    assert {"vehicle_id", "driver_id"} <= set(raised.value.fields)


def test_free_cars_and_delete(module: PrimavtodorModule) -> None:
    taken = make_vehicle(module, plate="Х1", model="Hino")
    spare = make_vehicle(module, plate="Л1", model="Lexus")
    driver = make_driver(module, taken["id"])
    created = book(module, taken, driver, "2026-10-07", "2026-10-09")

    free = module.bookings.free(date(2026, 10, 8), date(2026, 10, 8))
    assert [v["plate"] for v in free] == ["Л1"]
    assert spare["id"] == free[0]["id"]

    module.bookings.update(created["id"], {**created, "date_to": "2026-10-07"})
    assert len(module.bookings.free(date(2026, 10, 8), date(2026, 10, 8))) == 2
    module.bookings.delete(created["id"])
    assert module.bookings.overview(date(2026, 10, 1), 14, date(2026, 10, 8))["bookings"] == []

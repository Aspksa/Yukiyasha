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


def test_free_cars_and_drivers_on_a_day(module: PrimavtodorModule) -> None:
    taken = make_vehicle(module, plate="Х1", model="Hino")
    spare = make_vehicle(module, plate="Л1", model="Lexus")
    away = make_driver(module, taken["id"])
    book(module, taken, away, "2026-10-07", "2026-10-09")
    book(module, taken, away, "2026-10-12", "2026-10-13")

    free = module.bookings.overview(date(2026, 10, 5), 7, date(2026, 10, 8))["free"]
    assert [v["plate"] for v in free["vehicles"]] == ["Л1"] and free["drivers"] == []
    assert free["vehicles_total"] == 2 and free["drivers_total"] == 1

    later = module.bookings.overview(date(2026, 10, 5), 7, date(2026, 10, 8), date(2026, 10, 10))
    assert {v["plate"]: v["next"] for v in later["free"]["vehicles"]} == {
        "Х1": "2026-10-12",
        "Л1": None,
    }
    assert later["free"]["drivers"][0]["next"] == "2026-10-12"
    assert spare["id"] in {v["id"] for v in later["free"]["vehicles"]}


def test_timesheet_leave_and_sick_days_take_the_driver_off_the_list(
    module: PrimavtodorModule,
) -> None:
    car = make_vehicle(module, plate="Х1", model="Hino")
    sick = make_driver(module, car["id"])
    for day in ("2026-10-07", "2026-10-08", "2026-10-09"):
        module.timesheet.set_mark("2026-10", sick["id"], day, "Б")

    view = module.bookings.overview(date(2026, 10, 5), 7, date(2026, 10, 8))
    assert view["free"]["drivers"] == [] and view["free"]["absent_total"] == 1
    assert view["absent_now"][0]["label"] == "на больничном"
    assert view["absent_now"][0]["date_to"] == "2026-10-09"

    booked = book(module, car, sick, "2026-10-09", "2026-10-10")
    assert any("больничном" in text for text in booked["conflicts"])  # warned, not forbidden

    back = module.bookings.overview(date(2026, 10, 5), 7, date(2026, 10, 8), date(2026, 10, 11))
    assert len(back["free"]["drivers"]) == 1  # leave is over, the trip is over


# ----- one typed line -----


@pytest.fixture
def crew(module: PrimavtodorModule) -> dict:
    hino = make_vehicle(module, plate="С 303 СС", model="HINO 500")
    lexus = make_vehicle(module, plate="Л 777 ЛЛ", model="Lexus LX")
    verovsky = module.data.create(
        "employees",
        {"full_name": "Веровский Игорь Павлович", "is_driver": True, "vehicle_id": hino["id"]},
    )
    igor = module.data.create(
        "employees",
        {"full_name": "Орлов Игорь Сергеевич", "is_driver": True, "vehicle_id": lexus["id"]},
    )
    return {"hino": hino, "lexus": lexus, "verovsky": verovsky, "igor": igor}


TODAY = date(2026, 10, 6)


def test_surname_dates_and_kind_make_a_booking_with_the_drivers_car(module, crew) -> None:
    guess = module.bookings.parse("Веровский 7-9 командировка Находка", TODAY)

    assert guess["ok"], guess["problems"]
    assert guess["values"] == {
        "vehicle_id": crew["hino"]["id"],
        "driver_id": crew["verovsky"]["id"],
        "date_from": "2026-10-07",
        "date_to": "2026-10-09",
        "kind": "trip",
        "note": "Находка",
    }
    assert guess["preview"]["driver"] == "Веровский Игорь Павлович"


def test_declension_plate_and_the_other_car(module, crew) -> None:
    guess = module.bookings.parse("дай Веровскому лексус с 10 по 12 занят", TODAY)

    assert guess["ok"], guess["problems"]
    assert guess["values"]["driver_id"] == crew["verovsky"]["id"]
    assert guess["values"]["vehicle_id"] == crew["lexus"]["id"]  # named, not the assigned one
    assert guess["values"]["kind"] == "busy"

    by_plate = module.bookings.parse("л777лл 8", TODAY)
    assert by_plate["values"]["vehicle_id"] == crew["lexus"]["id"]
    assert by_plate["values"]["driver_id"] == crew["igor"]["id"]  # the car's driver
    assert by_plate["values"]["date_from"] == by_plate["values"]["date_to"] == "2026-10-08"


def test_an_ambiguous_name_is_not_guessed(module, crew) -> None:
    guess = module.bookings.parse("Игорь 7-9", TODAY)

    assert not guess["ok"]
    assert {c["name"] for c in guess["candidates"]["drivers"]} == {
        "Веровский Игорь Павлович",
        "Орлов Игорь Сергеевич",
    }


def test_dates_cross_the_month_and_unknown_people_are_reported(module, crew) -> None:
    guess = module.bookings.parse("Веровский 30-2", date(2026, 10, 28))
    assert (guess["values"]["date_from"], guess["values"]["date_to"]) == (
        "2026-10-30",
        "2026-11-02",
    )

    nobody = module.bookings.parse("Иванов 7-9", TODAY)
    assert not nobody["ok"] and any("водител" in p for p in nobody["problems"])
    no_dates = module.bookings.parse("Веровский", TODAY)
    assert not no_dates["ok"] and any("дат" in p for p in no_dates["problems"])


def test_tomorrow_service_and_conflict_preview(module, crew) -> None:
    module.bookings.create(
        {"vehicle_id": crew["hino"]["id"], "driver_id": crew["verovsky"]["id"],
         "date_from": "2026-10-07", "date_to": "2026-10-07", "kind": "busy"}
    )  # fmt: skip

    guess = module.bookings.parse("Веровский завтра", TODAY)
    assert guess["values"]["date_from"] == "2026-10-07" and guess["conflicts"]

    service = module.bookings.parse("хино 12-13 ремонт", TODAY)
    assert service["ok"] and service["values"]["kind"] == "service"

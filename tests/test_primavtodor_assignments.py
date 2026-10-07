"""Cars and cards move between drivers; manual fill-ups; the tank's remainder stays with the car."""

from pathlib import Path

import pytest

from tests.test_primavtodor_import import CARD, PETROL, prepare, statement_rows, xlsx
from tests.test_primavtodor_records import make_driver, make_vehicle, make_waybill
from yukiyasha.modules.disk import DiskModule
from yukiyasha.modules.primavtodor import PrimavtodorModule, RecordValidationError


@pytest.fixture
def module(tmp_path: Path) -> PrimavtodorModule:
    disk = DiskModule(tmp_path / "disk")
    disk.start()
    primavtodor = PrimavtodorModule(disk)
    primavtodor.start()
    return primavtodor


def edit(module: PrimavtodorModule, driver: dict, **changes) -> dict:
    values = {**driver["values"], **changes}
    return module.data.update("employees", driver["id"], values)


# ----- history of cars and cards, kept in the employee -----


def test_changing_the_car_keeps_the_history(module: PrimavtodorModule) -> None:
    hino = make_vehicle(module, plate="Х1", model="Hino")
    lexus = make_vehicle(module, plate="Л1", model="Lexus")
    driver = make_driver(module, hino["id"])

    changed = edit(module, driver, vehicle_id=lexus["id"], assignment_date="2026-10-06")

    text = changed["computed"]["vehicle_history_text"]
    assert "Hino Х1: по 05.10.2026" in text and "Lexus Л1: с 06.10.2026" in text
    assert changed["values"]["vehicle_id"] == lexus["id"]  # the current one
    assert "assignment_date" not in {k for k, v in changed["values"].items() if v}
    assert "vehicle_history" not in changed["values"]  # kept beside the values, not in them


def test_a_lost_card_is_detached_and_another_attached(module: PrimavtodorModule) -> None:
    vehicle = make_vehicle(module)
    driver = make_driver(module, vehicle["id"], fuel_card_number="111")

    detached = edit(module, driver, fuel_card_number="", assignment_date="2026-10-10")
    attached = edit(module, detached, fuel_card_number="222", assignment_date="2026-10-12")

    text = attached["computed"]["card_history_text"]
    assert "111: по 09.10.2026" in text and "222: с 12.10.2026" in text
    # the old card is free again for someone else
    other = make_driver(module, vehicle["id"], full_name="Петров", personnel_number="2",
                        fuel_card_number="111")  # fmt: skip
    assert other["values"]["fuel_card_number"] == "111"


def test_a_card_that_is_still_attached_to_another_driver_is_refused(
    module: PrimavtodorModule,
) -> None:
    vehicle = make_vehicle(module)
    make_driver(module, vehicle["id"], fuel_card_number="111")

    with pytest.raises(RecordValidationError) as exc:
        make_driver(module, vehicle["id"], full_name="Петров", personnel_number="2",
                    fuel_card_number="111")  # fmt: skip
    assert "fuel_card_number" in exc.value.fields


def test_a_fill_up_goes_to_the_car_the_driver_had_that_day(module: PrimavtodorModule) -> None:
    hino = make_vehicle(module, plate="Х1", model="Hino")
    lexus = make_vehicle(module, plate="Л1", model="Lexus")
    driver = make_driver(module, hino["id"], fuel_card_number="111")
    edit(module, driver, vehicle_id=lexus["id"], assignment_date="2026-10-06")

    before = module.data.create("fuel", {"driver_id": driver["id"], "date": "2026-10-04",
                                         "liters": 10})  # fmt: skip
    after = module.data.create("fuel", {"driver_id": driver["id"], "date": "2026-10-08",
                                        "liters": 10})  # fmt: skip

    assert before["values"]["vehicle_id"] == hino["id"]  # the Hino at that time
    assert after["values"]["vehicle_id"] == lexus["id"]


def test_the_statement_finds_the_card_holder_of_that_day(module: PrimavtodorModule) -> None:
    vehicle = make_vehicle(module)
    old = make_driver(module, vehicle["id"], fuel_card_number=CARD)
    edit(module, old, fuel_card_number="", assignment_date="2026-10-10")  # card taken away
    new = make_driver(module, vehicle["id"], full_name="Петров Пётр", personnel_number="2",
                      fuel_card_number="")  # fmt: skip
    edit(module, new, fuel_card_number=CARD, assignment_date="2026-10-10")
    rows = statement_rows((CARD, [("07.10.2026", "09:00:00", PETROL, 70.0, 10.0),
                                  ("15.10.2026", "09:00:00", PETROL, 70.0, 20.0)]))  # fmt: skip

    report = module.import_fuel_statement(xlsx(rows), "s.xlsx", apply=True)

    drivers = {op["date"]: op["driver"] for op in report["operations"]}
    assert drivers["2026-10-07"].startswith("Иванов")  # held it then
    assert drivers["2026-10-15"].startswith("Петров")  # holds it now
    assert report["counts"]["new"] == 2


def test_an_old_statement_still_matches_after_the_card_changed(module: PrimavtodorModule) -> None:
    waybill = prepare(module)
    content = xlsx(statement_rows((CARD, [("07.10.2026", "09:17:16", PETROL, 70.0, 40.0)])))
    module.import_fuel_statement(content, "s.xlsx", apply=True)
    driver = module.data.get("employees", waybill["values"]["driver_id"])
    edit(module, driver, fuel_card_number="7001000099999", assignment_date="2026-10-20")

    again = module.import_fuel_statement(content, "s2.xlsx", apply=True)

    assert again["counts"]["duplicate"] == 1 and len(module.data.snapshot("fuel")) == 1


# ----- manual fill-ups: cash and no card -----


def test_a_cash_fill_up_needs_no_card(module: PrimavtodorModule) -> None:
    vehicle = make_vehicle(module, plate="Н1", fuel_type="АИ-92")
    driver = make_driver(module, vehicle["id"], fuel_card_number="")  # no card at all

    cash = module.data.create("fuel", {"vehicle_id": vehicle["id"], "date": "2026-10-05",
                                       "liters": 20, "payment": "cash", "price_per_liter": 60})
    other = module.data.create("fuel", {"driver_id": driver["id"], "date": "2026-10-06",
                                        "liters": 15, "payment": "other"})  # fmt: skip

    assert cash["values"]["card_number"] is None and cash["values"]["driver_id"] is None
    assert cash["values"]["fuel_type"] == "АИ-92" and cash["computed"]["amount"] == 1200
    assert cash["computed"]["payment_label"] == "За наличные"
    assert other["values"]["vehicle_id"] == vehicle["id"]  # the driver's car
    with pytest.raises(RecordValidationError) as exc:  # a card payment still needs a card
        module.data.create("fuel", {"driver_id": driver["id"], "date": "2026-10-06", "liters": 5})
    assert "driver_id" in exc.value.fields


def test_cash_fill_ups_count_for_the_car_and_are_not_card_duplicates(
    module: PrimavtodorModule,
) -> None:
    vehicle = make_vehicle(module, plate="Н2", fuel_type="АИ-95", norm_summer="10")
    driver = make_driver(module, vehicle["id"], fuel_card_number=CARD)
    make_waybill(module, driver, vehicle, number="1", date="2026-10-07", season="summer",
                 odometer_out=0, odometer_in=100, fuel_out=10, fuel_in=5)  # fmt: skip
    module.data.create("fuel", {"vehicle_id": vehicle["id"], "date": "2026-10-07", "liters": 40,
                                "payment": "cash"})  # fmt: skip
    rows = statement_rows((CARD, [("07.10.2026", "09:00:00", PETROL, 70.0, 40.0)]))

    report = module.import_fuel_statement(xlsx(rows), "s.xlsx", apply=True)  # same litres, day

    assert report["counts"]["new"] == 1 and report["counts"]["duplicate"] == 0
    car = module.month_calculations("2026-10")["vehicles"][0]
    assert car["fills"] == 80 and car["fuel_kind"] == "petrol"


# ----- the remainder in the tank goes with the car -----


def test_the_next_driver_starts_with_the_remainder_of_the_car(module: PrimavtodorModule) -> None:
    vehicle = make_vehicle(module)
    first = make_driver(module, vehicle["id"], full_name="Иванов", personnel_number="1",
                        fuel_card_number="1")  # fmt: skip
    second = make_driver(module, vehicle["id"], full_name="Петров", personnel_number="2",
                         fuel_card_number="2")  # fmt: skip
    make_waybill(module, first, vehicle, number="1", date="2026-10-05", season="summer",
                 odometer_out=0, odometer_in=100, fuel_out=40, fuel_in=17.5)  # fmt: skip

    shown = module.data.get("vehicles", vehicle["id"])["computed"]
    taken = module.data.create("waybills", {"number": "2", "date": "2026-10-06",
                                            "driver_id": second["id"], "vehicle_id": vehicle["id"],
                                            "odometer_out": 100})  # fuel_out not given

    assert shown["fuel_remainder"] == 17.5 and "Иванов" in shown["remainder_note"]
    assert taken["values"]["fuel_out"] == 17.5  # carried over to the next driver
    explicit = module.data.create("waybills", {"number": "3", "date": "2026-10-07",
                                               "driver_id": second["id"],
                                               "vehicle_id": vehicle["id"], "odometer_out": 100,
                                               "fuel_out": 30})  # fmt: skip
    assert explicit["values"]["fuel_out"] == 30  # what the person typed wins


def test_a_driver_on_two_cars_keeps_each_cars_own_balance(module: PrimavtodorModule) -> None:
    hino = make_vehicle(module, plate="Х1", model="Hino", fuel_type="ДТ")
    lexus = make_vehicle(module, plate="Л1", model="Lexus", fuel_type="АИ-95")
    driver = make_driver(module, hino["id"])
    make_waybill(module, driver, hino, number="1", date="2026-10-05", season="summer",
                 odometer_out=0, odometer_in=100, fuel_out=50, fuel_in=40)  # fmt: skip
    make_waybill(module, driver, lexus, number="2", date="2026-10-06", season="summer",
                 odometer_out=0, odometer_in=100, fuel_out=20, fuel_in=12)  # fmt: skip

    assert module.data.get("vehicles", hino["id"])["computed"]["fuel_remainder"] == 40
    assert module.data.get("vehicles", lexus["id"])["computed"]["fuel_remainder"] == 12

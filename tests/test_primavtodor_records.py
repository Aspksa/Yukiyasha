"""Employees, vehicles, waybills, fuel and the timesheet, with their relations."""

import json
from pathlib import Path

import pytest

from yukiyasha.modules.disk import DiskModule
from yukiyasha.modules.primavtodor import (
    PrimavtodorModule,
    RecordInUseError,
    RecordNotFoundError,
    RecordValidationError,
    UnknownEntityError,
)


@pytest.fixture
def module(tmp_path: Path) -> PrimavtodorModule:
    disk = DiskModule(tmp_path / "disk")
    disk.start()
    primavtodor = PrimavtodorModule(disk)
    primavtodor.start()
    return primavtodor


def make_vehicle(module: PrimavtodorModule, **overrides: object) -> dict:
    values = {"plate": "а123 вб 125", "model": "КАМАЗ 65115", "fuel_type": "ДТ",
              "norm_summer": "30,5", "norm_winter": "36", "odometer_km": 120000}
    return module.data.create("vehicles", {**values, **overrides})


def make_driver(module: PrimavtodorModule, vehicle_id: str | None = None, **overrides) -> dict:
    values = {"full_name": "Иванов Иван Иванович", "position": "Водитель", "is_driver": True,
              "personnel_number": "101", "fuel_card_number": "7001 0000 1234",
              "vehicle_id": vehicle_id}
    return module.data.create("employees", {**values, **overrides})


def make_waybill(module: PrimavtodorModule, driver: dict, vehicle: dict, **overrides) -> dict:
    values = {"number": "1", "date": "2026-10-05", "driver_id": driver["id"],
              "vehicle_id": vehicle["id"], "route": "Владивосток — Уссурийск",
              "odometer_out": 120000, "fuel_out": 40}
    return module.data.create("waybills", {**values, **overrides})


def errors_of(exc: pytest.ExceptionInfo[RecordValidationError]) -> dict[str, str]:
    return exc.value.fields


# ----- vehicles & employees -----

def test_vehicle_is_normalised_and_stored_as_readable_json(module: PrimavtodorModule) -> None:
    vehicle = make_vehicle(module)

    assert vehicle["values"]["plate"] == "А123ВБ125"  # spaces removed, upper case
    assert vehicle["values"]["norm_summer"] == 30.5  # decimal comma accepted
    assert vehicle["values"]["norm_winter"] == 36
    assert vehicle["label"] == "А123ВБ125 · КАМАЗ 65115"
    stored = Path(module._disk.root) / "projects/work/Примавтодор/Гараж" / f"{vehicle['id']}.json"
    data = json.loads(stored.read_text(encoding="utf-8"))
    assert data["plate"] == "А123ВБ125" and data["id"] == vehicle["id"]


def test_driver_has_a_card_and_a_car(module: PrimavtodorModule) -> None:
    vehicle = make_vehicle(module)
    driver = make_driver(module, vehicle["id"])

    assert driver["values"]["fuel_card_number"] == "700100001234"  # spaces removed
    assert driver["labels"]["vehicle_id"] == "А123ВБ125 · КАМАЗ 65115"
    assert driver["warnings"] == []
    assert module.data.get("vehicles", vehicle["id"])["computed"]["drivers"] == (
        "Иванов Иван Иванович"
    )


def test_driver_without_card_or_car_gets_warnings_not_errors(module: PrimavtodorModule) -> None:
    driver = make_driver(module, None, fuel_card_number="")

    assert driver["warnings"] == ["Не закреплена топливная карта", "Не закреплена машина"]


def test_card_and_car_only_for_drivers(module: PrimavtodorModule) -> None:
    vehicle = make_vehicle(module)

    with pytest.raises(RecordValidationError) as exc:
        make_driver(module, vehicle["id"], is_driver=False, position="Бухгалтер")

    assert set(errors_of(exc)) == {"fuel_card_number", "vehicle_id"}


def test_unique_plate_card_and_personnel_number(module: PrimavtodorModule) -> None:
    vehicle = make_vehicle(module)
    make_driver(module, vehicle["id"])

    with pytest.raises(RecordValidationError) as plate:
        make_vehicle(module, plate="А123ВБ125")
    with pytest.raises(RecordValidationError) as employee:
        make_driver(module, None, full_name="Петров П.П.")

    assert "plate" in errors_of(plate)
    assert {"personnel_number", "fuel_card_number"} <= set(errors_of(employee))


def test_unknown_vehicle_reference_is_rejected(module: PrimavtodorModule) -> None:
    with pytest.raises(RecordValidationError) as exc:
        make_driver(module, "veh-deadbeef")

    assert "vehicle_id" in errors_of(exc)


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"plate": "", "model": "x"}, "plate"),
        ({"plate": "A1", "model": ""}, "model"),
        ({"plate": "A1", "model": "x", "norm_summer": "-1"}, "norm_summer"),
        ({"plate": "A1", "model": "x", "norm_winter": "abc"}, "norm_winter"),
        ({"plate": "A1", "model": "x", "odometer_km": "1.5"}, "odometer_km"),
        ({"plate": "A1", "model": "x", "fuel_type": "керосин"}, "fuel_type"),
        ({"plate": "A" * 40, "model": "x"}, "plate"),
    ],
)
def test_field_validation_messages(
    module: PrimavtodorModule, payload: dict, field: str
) -> None:
    with pytest.raises(RecordValidationError) as exc:
        module.data.create("vehicles", payload)

    assert field in errors_of(exc)


def test_update_replaces_values_and_keeps_created_at(module: PrimavtodorModule) -> None:
    vehicle = make_vehicle(module)

    updated = module.data.update(
        "vehicles", vehicle["id"], {"plate": "Б777ББ25", "model": "МАЗ", "fuel_type": "ДТ"}
    )

    assert updated["values"]["plate"] == "Б777ББ25"
    assert updated["created_at"] == vehicle["created_at"]
    assert module.data.get("vehicles", vehicle["id"])["values"]["model"] == "МАЗ"


def test_update_may_keep_its_own_unique_values(module: PrimavtodorModule) -> None:
    vehicle = make_vehicle(module)

    module.data.update("vehicles", vehicle["id"], {"plate": "А123ВБ125", "model": "Новая"})


def test_unknown_kind_and_missing_record(module: PrimavtodorModule) -> None:
    with pytest.raises(UnknownEntityError):
        module.data.list_records("nope")
    with pytest.raises(RecordNotFoundError):
        module.data.get("vehicles", "veh-00000000")
    with pytest.raises(RecordNotFoundError):
        module.data.get("vehicles", "../../etc/passwd")
    with pytest.raises(RecordNotFoundError):
        module.data.get("vehicles", "emp-00000000")  # an id of another kind


# ----- waybills -----

def test_waybill_computes_distance_fuel_and_norm(module: PrimavtodorModule) -> None:
    vehicle = make_vehicle(module, norm_summer=30)
    driver = make_driver(module, vehicle["id"])
    waybill = make_waybill(module, driver, vehicle)
    assert waybill["computed"]["status"] == "Открыт"
    assert waybill["computed"]["distance"] is None

    module.data.create(
        "fuel", {"waybill_id": waybill["id"], "date": "2026-10-05", "liters": 50}
    )
    closed = module.data.update(
        "waybills", waybill["id"],
        {**waybill["values"], "odometer_in": 120200, "fuel_in": 30},
    )

    computed = closed["computed"]
    assert computed["status"] == "Закрыт"
    assert computed["distance"] == 200
    assert computed["fuel_issued"] == 50
    assert computed["consumption"] == 60  # 40 at departure + 50 issued - 30 left
    assert computed["norm"] == 60  # 200 km * 30 l / 100 km
    assert computed["deviation"] == 0
    assert computed["driver_card"] == "700100001234"
    assert closed["warnings"] == []


def test_overrun_and_other_car_warnings(module: PrimavtodorModule) -> None:
    assigned = make_vehicle(module)
    other = make_vehicle(module, plate="В999ВВ25", norm_summer=20)
    driver = make_driver(module, assigned["id"])
    waybill = make_waybill(module, driver, other)
    module.data.create("fuel", {"waybill_id": waybill["id"], "date": "2026-10-05", "liters": 80})

    closed = module.data.update(
        "waybills", waybill["id"], {**waybill["values"], "odometer_in": 120100, "fuel_in": 10}
    )

    assert "Машина отличается от закреплённой за водителем" in closed["warnings"]
    assert "Перерасход топлива больше 10% от нормы" in closed["warnings"]
    assert closed["computed"]["deviation"] == 110 - 20  # 40 + 80 - 10 used, 20 allowed


def test_waybill_needs_a_driver_not_any_employee(module: PrimavtodorModule) -> None:
    vehicle = make_vehicle(module)
    clerk = make_driver(
        module, None, full_name="Сидорова", is_driver=False, fuel_card_number="",
        personnel_number="9",
    )

    with pytest.raises(RecordValidationError) as exc:
        make_waybill(module, clerk, vehicle)

    assert "driver_id" in errors_of(exc)


def test_waybill_closing_rules(module: PrimavtodorModule) -> None:
    vehicle = make_vehicle(module)
    driver = make_driver(module, vehicle["id"])

    with pytest.raises(RecordValidationError) as half:
        make_waybill(module, driver, vehicle, odometer_in=120100)
    with pytest.raises(RecordValidationError) as backwards:
        make_waybill(module, driver, vehicle, odometer_in=119000, fuel_in=5)
    with pytest.raises(RecordValidationError) as bad_date:
        make_waybill(module, driver, vehicle, date="05.10.2026")
    with pytest.raises(RecordValidationError) as no_number:
        make_waybill(module, driver, vehicle, number="")

    assert "fuel_in" in errors_of(half)
    assert "odometer_in" in errors_of(backwards)
    assert "date" in errors_of(bad_date)
    assert "number" in errors_of(no_number)


def test_waybill_numbers_are_unique(module: PrimavtodorModule) -> None:
    vehicle = make_vehicle(module)
    driver = make_driver(module, vehicle["id"])
    make_waybill(module, driver, vehicle)

    with pytest.raises(RecordValidationError) as exc:
        make_waybill(module, driver, vehicle, date="2026-10-06")

    assert "number" in errors_of(exc)


def test_waybills_are_listed_newest_first(module: PrimavtodorModule) -> None:
    vehicle = make_vehicle(module)
    driver = make_driver(module, vehicle["id"])
    make_waybill(module, driver, vehicle, number="1", date="2026-10-01")
    make_waybill(module, driver, vehicle, number="3", date="2026-10-09")
    make_waybill(module, driver, vehicle, number="2", date="2026-10-05")

    numbers = [r["values"]["number"] for r in module.data.list_records("waybills")["records"]]

    assert numbers == ["3", "2", "1"]


# ----- fuel -----

def test_fuel_takes_driver_car_and_card_from_the_waybill(module: PrimavtodorModule) -> None:
    vehicle = make_vehicle(module)
    driver = make_driver(module, vehicle["id"])
    waybill = make_waybill(module, driver, vehicle)

    fuel = module.data.create(
        "fuel",
        {"waybill_id": waybill["id"], "date": "2026-10-05", "liters": "45,5",
         "price_per_liter": 62, "station": "АЗС-1",
         # values the client must not be able to forge:
         "card_number": "FORGED", "driver_id": "emp-00000000"},
    )

    assert fuel["values"]["card_number"] == "700100001234"
    assert fuel["values"]["driver_id"] == driver["id"]
    assert fuel["values"]["vehicle_id"] == vehicle["id"]
    assert fuel["values"]["fuel_type"] == "ДТ"  # from the vehicle
    assert fuel["computed"]["driver"] == "Иванов Иван Иванович"
    assert fuel["computed"]["amount"] == 2821.0


def test_fuel_requires_a_card_on_the_driver(module: PrimavtodorModule) -> None:
    vehicle = make_vehicle(module)
    driver = make_driver(module, vehicle["id"], fuel_card_number="")
    waybill = make_waybill(module, driver, vehicle)

    with pytest.raises(RecordValidationError) as exc:
        module.data.create("fuel", {"waybill_id": waybill["id"], "date": "2026-10-05",
                                    "liters": 10})

    assert "топливная карта" in errors_of(exc)["waybill_id"]


def test_fuel_keeps_the_card_it_was_issued_on_when_the_driver_gets_a_new_one(
    module: PrimavtodorModule,
) -> None:
    vehicle = make_vehicle(module)
    driver = make_driver(module, vehicle["id"])
    waybill = make_waybill(module, driver, vehicle)
    fuel = module.data.create("fuel", {"waybill_id": waybill["id"], "date": "2026-10-05",
                                       "liters": 10})

    module.data.update("employees", driver["id"],
                       {**driver["values"], "fuel_card_number": "999"})

    assert module.data.get("fuel", fuel["id"])["values"]["card_number"] == "700100001234"


@pytest.mark.parametrize("liters", ["0", "-5", "abc", ""])
def test_fuel_liters_must_be_positive(module: PrimavtodorModule, liters: str) -> None:
    vehicle = make_vehicle(module)
    driver = make_driver(module, vehicle["id"])
    waybill = make_waybill(module, driver, vehicle)

    with pytest.raises(RecordValidationError) as exc:
        module.data.create("fuel", {"waybill_id": waybill["id"], "date": "2026-10-05",
                                    "liters": liters})

    assert "liters" in errors_of(exc)


# ----- integrity on delete -----

def test_records_that_are_referenced_cannot_be_deleted(module: PrimavtodorModule) -> None:
    vehicle = make_vehicle(module)
    driver = make_driver(module, vehicle["id"])
    waybill = make_waybill(module, driver, vehicle)
    fuel = module.data.create("fuel", {"waybill_id": waybill["id"], "date": "2026-10-05",
                                       "liters": 10})

    for kind, record in (("vehicles", vehicle), ("employees", driver), ("waybills", waybill)):
        with pytest.raises(RecordInUseError) as exc:
            module.data.delete(kind, record["id"])
        assert exc.value.references
        assert module.data.get(kind, record["id"])  # still there

    # Delete in the reverse order of the chain: fuel -> waybill -> driver -> vehicle.
    module.data.delete("fuel", fuel["id"])
    module.data.delete("waybills", waybill["id"])
    module.data.delete("employees", driver["id"])
    module.data.delete("vehicles", vehicle["id"])
    assert module.data.list_records("vehicles")["records"] == []


def test_a_broken_or_foreign_file_does_not_break_the_list(module: PrimavtodorModule) -> None:
    vehicle = make_vehicle(module)
    folder = Path(module._disk.root) / "projects/work/Примавтодор/Гараж"
    (folder / "veh-badbad00.json").write_text("{ not json", encoding="utf-8")
    (folder / "заметка.txt").write_text("my own note", encoding="utf-8")

    result = module.data.list_records("vehicles")

    assert [r["id"] for r in result["records"]] == [vehicle["id"]]
    assert result["problems"] == ["veh-badbad00.json"]


# ----- timesheet -----

def test_timesheet_marks_days_with_a_waybill_as_worked(module: PrimavtodorModule) -> None:
    vehicle = make_vehicle(module)
    driver = make_driver(module, vehicle["id"])
    office = make_driver(module, None, full_name="Бухгалтер", is_driver=False,
                         fuel_card_number="", personnel_number="5")
    make_waybill(module, driver, vehicle, number="1", date="2026-10-05",
                 odometer_in=120100, fuel_in=20)
    make_waybill(module, driver, vehicle, number="2", date="2026-10-06")
    make_waybill(module, driver, vehicle, number="3", date="2026-11-01")  # another month

    sheet = module.timesheet.month_view("2026-10")

    assert len(sheet["days"]) == 31
    rows = {row["name"]: row for row in sheet["rows"]}
    cells = {cell["date"]: cell for cell in rows["Иванов Иван Иванович"]["cells"]}
    assert cells["2026-10-05"]["code"] == "Я" and cells["2026-10-05"]["source"] == "waybill"
    assert cells["2026-10-07"]["code"] == ""
    assert rows["Иванов Иван Иванович"]["totals"]["worked"] == 2
    assert rows["Иванов Иван Иванович"]["totals"]["distance"] == 100
    assert rows["Бухгалтер"]["totals"]["worked"] == 0
    assert office["id"] == rows["Бухгалтер"]["employee_id"]


def test_manual_marks_override_and_flag_conflicts(module: PrimavtodorModule) -> None:
    vehicle = make_vehicle(module)
    driver = make_driver(module, vehicle["id"])
    make_waybill(module, driver, vehicle, date="2026-10-05")

    module.timesheet.set_mark("2026-10", driver["id"], "2026-10-05", "ОТ")
    module.timesheet.set_mark("2026-10", driver["id"], "2026-10-12", "Б")
    row = module.timesheet.month_view("2026-10")["rows"][0]
    cells = {cell["date"]: cell for cell in row["cells"]}

    assert cells["2026-10-05"]["code"] == "ОТ" and cells["2026-10-05"]["conflict"] is True
    assert cells["2026-10-12"]["code"] == "Б" and cells["2026-10-12"]["source"] == "manual"
    assert row["totals"]["by_code"] == {"ОТ": 1, "Б": 1}

    module.timesheet.set_mark("2026-10", driver["id"], "2026-10-05", None)  # back to automatic
    cells = {c["date"]: c for c in module.timesheet.month_view("2026-10")["rows"][0]["cells"]}
    assert cells["2026-10-05"]["code"] == "Я" and cells["2026-10-05"]["conflict"] is False


def test_timesheet_validation(module: PrimavtodorModule) -> None:
    driver = make_driver(module, None)

    for month in ("2026-13", "26-10", "abc", "2026-1", ""):
        with pytest.raises(RecordValidationError):
            module.timesheet.month_view(month)
    with pytest.raises(RecordValidationError):
        module.timesheet.set_mark("2026-10", driver["id"], "2026-11-01", "ОТ")  # other month
    with pytest.raises(RecordValidationError):
        module.timesheet.set_mark("2026-10", driver["id"], "2026-10-01", "ХХ")  # unknown code
    with pytest.raises(RecordNotFoundError):
        module.timesheet.set_mark("2026-10", "emp-00000000", "2026-10-01", "ОТ")


def test_inactive_employee_without_activity_is_left_out_of_the_timesheet(
    module: PrimavtodorModule,
) -> None:
    make_driver(module, None, full_name="Уволенный", active=False, personnel_number="7",
                fuel_card_number="")
    present = make_driver(module, None, full_name="Работает", personnel_number="8",
                          fuel_card_number="")

    names = [row["name"] for row in module.timesheet.month_view("2026-10")["rows"]]

    assert names == ["Работает"]
    assert present["id"]


# ----- summer / winter fuel norms -----

def season_waybill(module: PrimavtodorModule, driver: dict, vehicle: dict, **overrides) -> dict:
    """A closed 100 km waybill that used 20 l (40 out, 20 left, nothing fuelled)."""
    return make_waybill(
        module, driver, vehicle, odometer_in=120100, fuel_in=20, **overrides
    )


def test_each_vehicle_has_a_summer_and_a_winter_norm(module: PrimavtodorModule) -> None:
    vehicle = make_vehicle(module, norm_summer=30, norm_winter=36)
    driver = make_driver(module, vehicle["id"])

    summer = season_waybill(module, driver, vehicle, number="1", season="summer")
    winter = season_waybill(module, driver, vehicle, number="2", season="winter")

    assert summer["computed"]["norm_rate"] == 30 and summer["computed"]["norm"] == 30
    assert winter["computed"]["norm_rate"] == 36 and winter["computed"]["norm"] == 36
    assert summer["computed"]["season_label"] == "Лето"
    assert winter["computed"]["season_label"] == "Зима"
    assert winter["computed"]["deviation"] == 20 - 36  # 20 l used, 36 l allowed


def test_the_same_trip_is_an_overrun_in_summer_but_not_in_winter(
    module: PrimavtodorModule,
) -> None:
    vehicle = make_vehicle(module, norm_summer=15, norm_winter=30)
    driver = make_driver(module, vehicle["id"])

    summer = season_waybill(module, driver, vehicle, number="1", season="summer")
    winter = season_waybill(module, driver, vehicle, number="2", season="winter")

    assert "Перерасход топлива больше 10% от нормы" in summer["warnings"]
    assert "Перерасход топлива больше 10% от нормы" not in winter["warnings"]


def test_a_new_waybill_starts_in_the_current_season(module: PrimavtodorModule) -> None:
    vehicle = make_vehicle(module)
    driver = make_driver(module, vehicle["id"])
    module.data.apply_season("winter")

    waybill = make_waybill(module, driver, vehicle)

    assert waybill["values"]["season"] == "winter"


def test_vehicle_shows_the_norm_of_the_active_season(module: PrimavtodorModule) -> None:
    vehicle = make_vehicle(module, norm_summer=30, norm_winter=36)

    module.data.apply_season("summer")
    assert module.data.get("vehicles", vehicle["id"])["computed"]["norm_active"] == 30
    module.data.apply_season("winter")
    computed = module.data.get("vehicles", vehicle["id"])["computed"]
    assert computed["norm_active"] == 36 and computed["norm_active_season"] == "Зима"


def test_switching_the_season_moves_open_waybills_but_never_closed_ones(
    module: PrimavtodorModule,
) -> None:
    vehicle = make_vehicle(module)
    driver = make_driver(module, vehicle["id"])
    module.data.apply_season("summer")
    open_one = make_waybill(module, driver, vehicle, number="1")
    closed = season_waybill(module, driver, vehicle, number="2")

    result = module.data.apply_season("winter")

    assert result["season"] == "winter" and result["updated_waybills"] == 1
    assert module.data.get("waybills", open_one["id"])["values"]["season"] == "winter"
    kept = module.data.get("waybills", closed["id"])
    assert kept["values"]["season"] == "summer"
    assert kept["computed"]["norm_rate"] == 30.5  # history is untouched
    assert module.data.apply_season("winter")["updated_waybills"] == 0  # nothing left to move


def test_the_season_survives_a_restart(tmp_path: Path) -> None:
    disk = DiskModule(tmp_path / "disk")
    disk.start()
    first = PrimavtodorModule(disk)
    first.start()
    first.data.apply_season("winter")

    second = PrimavtodorModule(disk)  # a fresh instance reads the stored setting

    settings = second.settings.load()
    assert settings["season"] == "winter" and settings["source"] == "manual"
    stored = Path(disk.root) / "projects/work/Примавтодор/settings.json"
    assert json.loads(stored.read_text(encoding="utf-8"))["season"] == "winter"


def test_without_a_manual_choice_the_season_follows_the_calendar(
    module: PrimavtodorModule,
) -> None:
    from datetime import date

    from yukiyasha.modules.primavtodor.settings import default_season

    assert default_season(date(2026, 7, 15)) == "summer"
    assert default_season(date(2026, 1, 15)) == "winter"
    assert default_season(date(2026, 11, 1)) == "winter"
    assert default_season(date(2026, 3, 31)) == "winter"
    assert default_season(date(2026, 4, 1)) == "summer"
    assert module.settings.load()["source"] == "calendar"


def test_unknown_season_is_rejected(module: PrimavtodorModule) -> None:
    for bad in ("", "autumn", "WINTER"):
        with pytest.raises(RecordValidationError):
            module.data.apply_season(bad)
    with pytest.raises(RecordValidationError):
        make_waybill(module, make_driver(module, None), make_vehicle(module), season="spring")


def test_a_vehicle_without_a_norm_for_the_season_is_reported(module: PrimavtodorModule) -> None:
    vehicle = make_vehicle(module, norm_winter="")
    driver = make_driver(module, vehicle["id"])

    waybill = season_waybill(module, driver, vehicle, season="winter")

    assert waybill["computed"]["norm"] is None
    assert "Для машины не задана норма на сезон «Зима»" in waybill["warnings"]


def test_records_from_before_the_seasons_are_upgraded(module: PrimavtodorModule) -> None:
    """One yearly norm used to be stored as norm_per_100km; waybills had no season."""
    folder = Path(module._disk.root) / "projects/work/Примавтодор"
    legacy_vehicle = {"id": "veh-aaaaaaaa", "created_at": "2026-01-01T00:00:00+00:00",
                      "updated_at": "2026-01-01T00:00:00+00:00", "plate": "О001ОО25",
                      "model": "Старая", "fuel_type": "ДТ", "norm_per_100km": 25.0,
                      "odometer_km": 1, "active": True}
    (folder / "Гараж" / "veh-aaaaaaaa.json").write_text(
        json.dumps(legacy_vehicle, ensure_ascii=False), encoding="utf-8"
    )

    vehicle = module.data.get("vehicles", "veh-aaaaaaaa")

    assert vehicle["values"]["norm_summer"] == 25 and vehicle["values"]["norm_winter"] == 25
    assert "norm_per_100km" not in vehicle["values"]
    # editing and saving writes the upgraded shape back
    module.data.update("vehicles", "veh-aaaaaaaa", vehicle["values"])
    saved = json.loads((folder / "Гараж" / "veh-aaaaaaaa.json").read_text(encoding="utf-8"))
    assert "norm_per_100km" not in saved and saved["norm_summer"] == 25

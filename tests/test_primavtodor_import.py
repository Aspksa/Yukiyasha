"""Fuel-card statement: parsing, matching card -> driver -> waybill, no double loading."""

import io
from pathlib import Path

import openpyxl
import pytest
from fastapi.testclient import TestClient

from tests.test_primavtodor_records import make_driver, make_vehicle, make_waybill
from yukiyasha.config import Settings
from yukiyasha.modules.disk import DiskModule
from yukiyasha.modules.primavtodor import PrimavtodorModule, StatementError
from yukiyasha.modules.primavtodor import statement as statement_module
from yukiyasha.modules.primavtodor.statement import fuel_type_of, parse_statement
from yukiyasha.web.app import create_app

CARD = "7001000012340"
PETROL = "Бензин автомобильный марки Премиум Евро-95-К5 (АИ-95-К5)"
DIESEL = "Топливо дизельное ЕВРО, летнее, сорта С"


def statement_rows(*blocks: tuple[str, list[tuple]]) -> list[list]:
    rows: list[list] = [["Выписка по пластиковым картам"], [], ["ФИРМА"],
                        ["Период с 01.10.2026 по 31.10.2026"], []]  # fmt: skip
    for card, operations in blocks:
        rows.append([f"Карта №  {card}       Авто: "])
        rows.append(["Операция", "Дата", "Время", "Азс", "Топливо", "Цена", "Кол-во", "Сумма"])
        for day, time, fuel, price, liters in operations:
            rows.append(["Отгрузка", day, time, "АЗС - 1 г.Тест", fuel, price, liters,
                         price * liters])  # fmt: skip
        rows.append(["", "", "", "", "", "", "", 1.0])
        rows.append(["Итого по карте по виду топлива:"])
    return rows


def xlsx(rows: list[list]) -> bytes:
    workbook = openpyxl.Workbook()
    for row in rows:
        workbook.active.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


@pytest.fixture
def module(tmp_path: Path) -> PrimavtodorModule:
    disk = DiskModule(tmp_path / "disk")
    disk.start()
    primavtodor = PrimavtodorModule(disk)
    primavtodor.start()
    return primavtodor


def prepare(module: PrimavtodorModule) -> dict:
    vehicle = make_vehicle(module)
    driver = make_driver(module, vehicle["id"], fuel_card_number=CARD)
    return make_waybill(module, driver, vehicle, number="5", date="2026-10-07")


# ----- reading -----


def test_parse_reads_cards_operations_and_fuel_types() -> None:
    rows = statement_rows(
        (CARD, [("07.10.2026", "09:17:16", PETROL, 70.5, 40.0)]),
        ("7001000099990", [("08.10.2026", "10:00:00", DIESEL, 66.0, 20.0)]),
    )

    operations, period = parse_statement(xlsx(rows), "выписка.xlsx")

    assert period.startswith("Период с 01.10.2026")
    assert [(o.card, o.day.isoformat(), o.fuel_type, o.liters) for o in operations] == [
        (CARD, "2026-10-07", "АИ-95", 40.0),
        ("7001000099990", "2026-10-08", "ДТ", 20.0),
    ]
    assert operations[0].time == "09:17:16" and operations[0].price == 70.5


@pytest.mark.parametrize(
    ("content", "name"),
    [(b"not a workbook", "a.xlsx"), (b"x", "a.csv"), (xlsx([["пусто"]]), "a.xlsx")],
)
def test_parse_rejects_what_is_not_a_statement(content: bytes, name: str) -> None:
    with pytest.raises(StatementError):
        parse_statement(content, name)


def test_xls_is_read_as_windows_1251(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}
    rows = statement_rows((CARD, [("07.10.2026", "09:00:00", PETROL, 70.0, 10.0)]))

    class Sheet:
        nrows, ncols = len(rows), 8

        def cell_value(self, r: int, c: int):
            return rows[r][c] if c < len(rows[r]) else ""

    class Book:
        def sheet_by_index(self, index: int) -> Sheet:
            return Sheet()

    def fake_open(**kwargs):
        seen.update(kwargs)
        return Book()

    import xlrd

    monkeypatch.setattr(xlrd, "open_workbook", fake_open)

    operations, _ = statement_module.parse_statement(b"binary", "в.XLS")

    assert seen["encoding_override"] == "cp1251" and len(operations) == 1


def test_fuel_type_names() -> None:
    assert fuel_type_of("Бензин ... (АИ-92-К5)") == "АИ-92"
    assert fuel_type_of(DIESEL) == "ДТ" and fuel_type_of("что-то") == ""


# ----- matching and loading -----


def test_preview_changes_nothing_and_apply_creates_fuel_records(module) -> None:
    waybill = prepare(module)
    content = xlsx(statement_rows((CARD, [("07.10.2026", "09:17:16", PETROL, 70.0, 40.0)])))

    preview = module.import_fuel_statement(content, "s.xlsx", apply=False)
    assert preview["counts"] == {"total": 1, "new": 1, "duplicate": 0, "unmatched": 0, "failed": 0}
    assert module.data.snapshot("fuel") == []

    done = module.import_fuel_statement(content, "s.xlsx", apply=True)

    assert done["counts"]["new"] == 1 and done["operations"][0]["waybill"] == "5"
    (fuel,) = module.data.snapshot("fuel")
    assert fuel["waybill_id"] == waybill["id"] and fuel["liters"] == 40.0
    assert fuel["time"] == "09:17:16" and fuel["card_number"] == CARD
    assert fuel["fuel_type"] == "АИ-95" and fuel["price_per_liter"] == 70.0


def test_loading_twice_creates_nothing_twice(module) -> None:
    prepare(module)
    content = xlsx(statement_rows((CARD, [("07.10.2026", "09:17:16", PETROL, 70.0, 40.0)])))
    module.import_fuel_statement(content, "s.xlsx", apply=True)

    again = module.import_fuel_statement(content, "s.xlsx", apply=True)

    assert again["counts"]["duplicate"] == 1 and again["counts"]["new"] == 0
    assert len(module.data.snapshot("fuel")) == 1


def test_a_hand_entered_fill_up_counts_as_a_duplicate(module) -> None:
    waybill = prepare(module)
    module.data.create("fuel", {"waybill_id": waybill["id"], "date": "2026-10-07", "liters": 40})
    content = xlsx(statement_rows((CARD, [("07.10.2026", "09:17:16", PETROL, 70.0, 40.0)])))

    report = module.import_fuel_statement(content, "s.xlsx", apply=True)

    assert report["counts"]["duplicate"] == 1 and len(module.data.snapshot("fuel")) == 1


def test_unmatched_operations_are_reported_with_the_reason(module) -> None:
    prepare(module)
    rows = statement_rows(
        ("7009999999999", [("07.10.2026", "09:00:00", PETROL, 70.0, 10.0)]),  # unknown card
        (CARD, [("20.10.2026", "09:00:00", PETROL, 70.0, 10.0)]),  # no waybill that day
    )

    report = module.import_fuel_statement(xlsx(rows), "s.xlsx", apply=True)

    reasons = [str(op["reason"]) for op in report["operations"]]
    assert report["counts"]["unmatched"] == 2 and module.data.snapshot("fuel") == []
    assert "не закреплена ни за одним сотрудником" in reasons[0]
    assert "Нет путевого листа за 20.10.2026" in reasons[1]


def test_two_waybills_on_one_day_are_not_guessed(module) -> None:
    waybill = prepare(module)
    driver, vehicle = waybill["values"]["driver_id"], waybill["values"]["vehicle_id"]
    module.data.create(
        "waybills",
        {"number": "6", "date": "2026-10-07", "driver_id": driver, "vehicle_id": vehicle,
         "odometer_out": 1, "fuel_out": 0},
    )  # fmt: skip
    content = xlsx(statement_rows((CARD, [("07.10.2026", "09:00:00", PETROL, 70.0, 10.0)])))

    report = module.import_fuel_statement(content, "s.xlsx", apply=True)

    assert report["counts"]["unmatched"] == 1
    assert "Несколько путевых листов" in str(report["operations"][0]["reason"])


# ----- HTTP -----


@pytest.fixture
def client(tmp_path: Path):
    app = create_app(Settings(disk_dir=tmp_path / "disk"))
    with TestClient(app, base_url="http://127.0.0.1:8000") as test_client:
        yield test_client


def test_import_over_http(client: TestClient) -> None:
    vehicle = client.post("/api/primavtodor/records/vehicles",
                          json={"plate": "А1", "model": "Т"}).json()  # fmt: skip
    driver = client.post(
        "/api/primavtodor/records/employees",
        json={"full_name": "Иванов Иван", "is_driver": True, "fuel_card_number": CARD},
    ).json()
    client.post(
        "/api/primavtodor/records/waybills",
        json={"number": "1", "date": "2026-10-07", "driver_id": driver["id"],
              "vehicle_id": vehicle["id"], "odometer_out": 5},
    )  # fmt: skip
    content = xlsx(statement_rows((CARD, [("07.10.2026", "09:00:00", PETROL, 70.0, 10.0)])))
    url = "/api/primavtodor/fuel/import"
    headers = {"Content-Type": "application/octet-stream"}

    preview = client.post(url, params={"filename": "в.xlsx"}, content=content, headers=headers)
    applied = client.post(
        url, params={"filename": "в.xlsx", "apply": "true"}, content=content, headers=headers
    )
    bad = client.post(url, params={"filename": "в.txt"}, content=b"zzz", headers=headers)

    assert preview.status_code == 200 and preview.json()["counts"]["new"] == 1
    assert applied.json()["applied"] is True
    assert len(client.get("/api/primavtodor/records/fuel").json()["records"]) == 1
    assert bad.status_code == 422 and "xlsx" in bad.json()["detail"]["message"]

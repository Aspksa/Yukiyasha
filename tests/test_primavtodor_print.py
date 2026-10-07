"""Printable waybill (form № 3): values reach both halves of the sheet, settings, the API."""

import io
from pathlib import Path

import openpyxl
import pytest
from fastapi.testclient import TestClient

from tests.test_primavtodor_records import make_driver, make_vehicle, make_waybill
from yukiyasha.config import Settings
from yukiyasha.modules.disk import DiskModule
from yukiyasha.modules.primavtodor import (
    PrimavtodorModule,
    PrintNotAvailableError,
    RecordValidationError,
)
from yukiyasha.modules.primavtodor.printing import COPY_OFFSET, short_name
from yukiyasha.web.app import create_app

OFFSET = COPY_OFFSET
PRINT_SETTINGS = {
    "org_name": 'АО "ТЕСТ"', "org_header": "Тестовая шапка", "unit": "Дирекции",
    "address": "По городу", "mechanic": "Сидоров С. С.", "dispatcher": "Иванов И. И.",
    "control": "mechanic",
}  # fmt: skip


@pytest.fixture
def module(tmp_path: Path) -> PrimavtodorModule:
    disk = DiskModule(tmp_path / "disk")
    disk.start()
    primavtodor = PrimavtodorModule(disk)
    primavtodor.start()
    return primavtodor


def cells(content: bytes) -> openpyxl.worksheet.worksheet.Worksheet:
    return openpyxl.load_workbook(io.BytesIO(content))["Лист1"]


def both(sheet, left: str):
    """The value of a cell in the waybill and in its copy."""
    from yukiyasha.modules.primavtodor.printing import _shift

    def read(coordinate: str):
        for merged in sheet.merged_cells.ranges:
            if coordinate in merged:
                coordinate = merged.start_cell.coordinate
        return sheet[coordinate].value

    return read(left), read(_shift(left, OFFSET))


def closed_waybill(module: PrimavtodorModule) -> dict:
    vehicle = make_vehicle(
        module, plate="А123ВС125", model="TOYOTA TEST", fuel_type="АИ-95",
        garage_number="12", norm_summer="12", waybill_form="car",
    )  # fmt: skip
    driver = make_driver(
        module, vehicle["id"], full_name="Петров Пётр Петрович", personnel_number="77",
        license_number="99 00 000000", license_class="B, C",
    )  # fmt: skip
    waybill = make_waybill(
        module, driver, vehicle, number="42", date="2026-10-07", season="summer",
        odometer_out=1000, odometer_in=1100, fuel_out=20, fuel_in=15,
        time_out="8:00", time_in="17:30",
    )  # fmt: skip
    module.data.create(
        "fuel", {"waybill_id": waybill["id"], "date": "2026-10-07", "liters": 10}
    )
    module.settings.set_print_settings(PRINT_SETTINGS)
    return module.data.get("waybills", waybill["id"])


def test_values_land_in_both_halves_of_the_form(module: PrimavtodorModule) -> None:
    waybill = closed_waybill(module)

    content, name = module.print_waybill(waybill["id"])

    sheet = cells(content)
    assert name == "Путевой лист № 42.xlsx"
    expected = {
        "BX4": "42", "AD5": "07", "AI5": "октября", "AU5": "2026", "R8": 'АО "ТЕСТ"',
        "V10": "TOYOTA TEST", "AI11": "А123ВС125", "BP11": "12", "M12": "Петров Пётр Петрович",
        "BP12": "77", "S14": "99 00 000000", "BO14": "B, C", "BR19": "1000", "Q20": "Дирекции",
        "BN22": "Сидоров С. С.", "R26": "По городу", "BP26": "Петров П. П.", "BF28": "АИ-95",
        "AE29": "08:00", "AE33": "17:30", "AD31": "Иванов И. И.", "BT33": "10", "BT36": "20",
        "BT37": "15", "BT38": "12", "BT39": "15", "BT41": "3", "BT44": "1100",
        "AU21": "Выезд разрешен", "AU22": "Механик", "C1": "Тестовая шапка",
    }  # fmt: skip
    for coordinate, value in expected.items():
        assert both(sheet, coordinate) == (value, value), coordinate
    assert both(sheet, "BT40") == (None, None)  # no saving when there is an overrun


def test_template_carries_no_personal_data(module: PrimavtodorModule) -> None:
    waybill = module.data.create("waybills", _bare_waybill(module))
    sheet = cells(module.print_waybill(waybill["id"])[0])

    for coordinate in ("V10", "AI11", "M12", "S14", "Q20", "BN22", "R26", "C1", "AD31"):
        assert both(sheet, coordinate)[0] not in {"Вазанов", "Матиенко"}
    texts = [str(c.value) for row in sheet.iter_rows() for c in row if c.value]
    assert not any(word in " ".join(texts) for word in ("Вазанов", "Матиенко", "Бредюк", "707"))


def _bare_waybill(module: PrimavtodorModule) -> dict:
    vehicle = make_vehicle(module)
    driver = make_driver(module, vehicle["id"])
    return {"number": "1", "date": "2026-10-05", "driver_id": driver["id"],
            "vehicle_id": vehicle["id"], "odometer_out": 10, "fuel_out": 0}  # fmt: skip


def test_controller_wording_and_saving(module: PrimavtodorModule) -> None:
    waybill = closed_waybill(module)
    module.settings.set_print_settings({**PRINT_SETTINGS, "control": "controller"})
    module.data.update(
        "waybills", waybill["id"], {**waybill["values"], "fuel_in": 19, "odometer_in": 1100}
    )

    sheet = cells(module.print_waybill(waybill["id"])[0])

    assert both(sheet, "AU22") == ("Контролер", "Контролер")
    assert both(sheet, "AU21")[0].startswith("Предрейсовый контроль")
    assert both(sheet, "BT40") == ("1", "1")  # 11 l used against a 12 l norm
    assert both(sheet, "BT41") == (None, None)


def test_open_waybill_prints_without_the_closing_block(module: PrimavtodorModule) -> None:
    waybill = module.data.create("waybills", _bare_waybill(module))

    sheet = cells(module.print_waybill(waybill["id"])[0])

    assert both(sheet, "BT37") == (None, None) and both(sheet, "BT44") == (None, None)
    assert both(sheet, "BR19") == ("10", "10")


def test_other_forms_are_refused_with_a_clear_message(module: PrimavtodorModule) -> None:
    vehicle = make_vehicle(module, waybill_form="truck")
    driver = make_driver(module, vehicle["id"])
    waybill = make_waybill(module, driver, vehicle)

    with pytest.raises(PrintNotAvailableError, match="№ 4-П"):
        module.print_waybill(waybill["id"])


def test_time_is_validated_and_normalised(module: PrimavtodorModule) -> None:
    vehicle = make_vehicle(module)
    driver = make_driver(module, vehicle["id"])
    ok = make_waybill(module, driver, vehicle, time_out="7:05")
    assert ok["values"]["time_out"] == "07:05"
    with pytest.raises(RecordValidationError) as exc:
        make_waybill(module, driver, vehicle, number="2", time_in="25:00")
    assert "time_in" in exc.value.fields


def test_print_settings_keep_the_season_and_validate(module: PrimavtodorModule) -> None:
    module.settings.set_season("winter")
    saved = module.settings.set_print_settings(PRINT_SETTINGS)

    assert saved["mechanic"] == "Сидоров С. С." and module.settings.season() == "winter"
    module.settings.set_season("summer")  # switching the season must not wipe the print data
    assert module.settings.print_settings()["org_name"] == 'АО "ТЕСТ"'
    with pytest.raises(RecordValidationError):
        module.settings.set_print_settings({"control": "boss", "mechanic": "x" * 400})


def test_short_name() -> None:
    assert short_name("Иванов Иван Иванович") == "Иванов И. И."
    assert short_name("Иванов") == "Иванов"
    assert short_name("") == ""


# ----- HTTP -----


@pytest.fixture
def client(tmp_path: Path):
    app = create_app(Settings(disk_dir=tmp_path / "disk"))
    with TestClient(app, base_url="http://127.0.0.1:8000") as test_client:
        yield test_client


def test_print_over_http(client: TestClient) -> None:
    vehicle = client.post(
        "/api/primavtodor/records/vehicles",
        json={"plate": "А1", "model": "Т", "garage_number": "5"},
    ).json()
    driver = client.post(
        "/api/primavtodor/records/employees",
        json={"full_name": "Иванов Иван Иванович", "is_driver": True},
    ).json()
    waybill = client.post(
        "/api/primavtodor/records/waybills",
        json={"number": "7/1", "date": "2026-10-07", "driver_id": driver["id"],
              "vehicle_id": vehicle["id"], "odometer_out": 5},
    ).json()  # fmt: skip
    assert client.put("/api/primavtodor/settings/print", json=PRINT_SETTINGS).status_code == 200
    assert client.get("/api/primavtodor/settings/print").json()["values"]["unit"] == "Дирекции"

    response = client.get(f"/api/primavtodor/waybills/{waybill['id']}/print")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert "filename*=UTF-8''" in response.headers["content-disposition"]
    assert "7-1" in response.headers["content-disposition"] or "7%2D1" in response.headers[
        "content-disposition"
    ]
    assert both(cells(response.content), "BX4") == ("7/1", "7/1")
    assert client.get("/api/primavtodor/waybills/wb-00000000/print").status_code == 404
    bad = client.put("/api/primavtodor/settings/print", json={"control": "boss"})
    assert bad.status_code == 422 and "control" in bad.json()["detail"]["fields"]


def test_print_of_another_form_is_a_422_with_a_message(client: TestClient) -> None:
    vehicle = client.post(
        "/api/primavtodor/records/vehicles",
        json={"plate": "Г1", "model": "ХИНО", "waybill_form": "truck"},
    ).json()
    driver = client.post(
        "/api/primavtodor/records/employees", json={"full_name": "Пётр Петров", "is_driver": True}
    ).json()
    waybill = client.post(
        "/api/primavtodor/records/waybills",
        json={"number": "1", "date": "2026-10-07", "driver_id": driver["id"],
              "vehicle_id": vehicle["id"], "odometer_out": 5},
    ).json()  # fmt: skip

    response = client.get(f"/api/primavtodor/waybills/{waybill['id']}/print")

    assert response.status_code == 422 and "№ 4-П" in response.json()["detail"]["message"]

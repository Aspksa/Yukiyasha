"""Control of fuel use and the closing of a month."""

import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_primavtodor_records import make_driver, make_vehicle, make_waybill
from yukiyasha.config import Settings
from yukiyasha.modules.disk import DiskModule
from yukiyasha.modules.primavtodor import PrimavtodorModule, RecordValidationError
from yukiyasha.web.app import create_app


@pytest.fixture
def module(tmp_path: Path) -> PrimavtodorModule:
    disk = DiskModule(tmp_path / "disk")
    disk.start()
    primavtodor = PrimavtodorModule(disk)
    primavtodor.start()
    return primavtodor


def codes(module: PrimavtodorModule, month: str = "2026-10", **kw) -> dict[str, dict]:
    findings = module.month_review(month, **kw)["findings"]
    return {f["code"]: f for f in findings}


def car(module: PrimavtodorModule, **overrides) -> tuple[dict, dict]:
    vehicle = make_vehicle(module, norm_summer="10", fuel_type="АИ-95", tank_liters="60",
                           **overrides)  # fmt: skip
    driver = make_driver(module, vehicle["id"])
    return vehicle, driver


def test_a_clean_month_has_no_findings(module: PrimavtodorModule) -> None:
    vehicle, driver = car(module)
    make_waybill(module, driver, vehicle, number="1", date="2026-10-07", season="summer",
                 odometer_out=1000, odometer_in=1100, fuel_out=30, fuel_in=20)  # fmt: skip

    review = module.month_review("2026-10")

    assert review["findings"] == [] and review["ready"] is True
    assert [s["status"] for s in review["steps"]][:1] == ["ok"]


def test_overrun_and_underrun_and_zero_fuel(module: PrimavtodorModule) -> None:
    vehicle, driver = car(module)
    make_waybill(module, driver, vehicle, number="1", date="2026-10-05", season="summer",
                 odometer_out=0, odometer_in=100, fuel_out=40, fuel_in=20)  # 20 l vs norm 10
    make_waybill(module, driver, vehicle, number="2", date="2026-10-06", season="summer",
                 odometer_out=100, odometer_in=200, fuel_out=20, fuel_in=16)  # 4 l: too little
    make_waybill(module, driver, vehicle, number="3", date="2026-10-07", season="summer",
                 odometer_out=200, odometer_in=300, fuel_out=16, fuel_in=16)  # 0 l

    found = module.month_review("2026-10")["findings"]

    by_code = {(f["code"], f["severity"]) for f in found}
    assert ("OVERRUN", "error") in by_code  # +100% of the norm
    assert ("UNDERRUN", "warn") in by_code and ("ZERO_FUEL", "warn") in by_code
    assert found[0]["severity"] == "error"  # the worst first


def test_odometer_and_fuel_continuity(module: PrimavtodorModule) -> None:
    vehicle, driver = car(module)
    make_waybill(module, driver, vehicle, number="1", date="2026-10-05", season="summer",
                 odometer_out=1000, odometer_in=1100, fuel_out=30, fuel_in=20)  # fmt: skip
    make_waybill(module, driver, vehicle, number="2", date="2026-10-06", season="summer",
                 odometer_out=1200, odometer_in=1300, fuel_out=25, fuel_in=15)  # gaps
    make_waybill(module, driver, vehicle, number="3", date="2026-10-07", season="summer",
                 odometer_out=1250, odometer_in=1350, fuel_out=15, fuel_in=5)  # went back

    found = codes(module)

    assert found["ODO_GAP"]["detail"].startswith("Между листом № 1")
    assert found["FUEL_GAP"]["severity"] == "warn"
    assert found["ODO_REWIND"]["severity"] == "error"


def test_fuel_rules(module: PrimavtodorModule) -> None:
    vehicle, driver = car(module)
    waybill = make_waybill(module, driver, vehicle, number="1", date="2026-10-07",
                           season="summer")  # fmt: skip
    module.data.create("fuel", {"waybill_id": waybill["id"], "date": "2026-10-07",
                                "liters": 70, "fuel_type": "ДТ"})  # fmt: skip
    module.data.create("fuel", {"waybill_id": waybill["id"], "date": "2026-10-09",
                                "liters": 10})  # fmt: skip

    found = module.month_review("2026-10")["findings"]

    pairs = {(f["code"], f["severity"]) for f in found}
    assert ("WRONG_FUEL", "error") in pairs  # diesel into a petrol car
    assert ("OVER_TANK", "error") in pairs  # 70 l into a 60 l tank
    assert ("OVER_TANK", "warn") in pairs  # and the waybill holds more than the tank
    assert ("FUEL_DATE", "warn") in pairs


def test_open_old_waybill_double_driver_and_day_off(module: PrimavtodorModule) -> None:
    vehicle, driver = car(module)
    other = make_vehicle(module, plate="Б2", model="Вторая")
    make_waybill(module, driver, vehicle, number="1", date="2026-10-03")  # Saturday, never closed
    make_waybill(module, driver, other, number="2", date="2026-10-03", odometer_out=5)

    found = codes(module)

    assert found["OPEN_OLD"]["severity"] == "warn"
    assert found["DOUBLE_DRIVER"]["severity"] == "warn"
    assert found["OFF_DAY"]["severity"] == "info"


def test_a_finding_can_be_accepted_and_restored(module: PrimavtodorModule) -> None:
    vehicle, driver = car(module)
    make_waybill(module, driver, vehicle, number="1", date="2026-10-05", season="summer",
                 odometer_out=0, odometer_in=100, fuel_out=40, fuel_in=20)  # fmt: skip
    finding = module.month_review("2026-10")["findings"][0]

    module.dismiss_finding(finding["id"], "Возили груз, согласовано")
    after = module.month_review("2026-10")
    shown = module.month_review("2026-10", show_dismissed=True)

    assert finding["id"] not in {f["id"] for f in after["findings"]}
    assert after["counts"]["dismissed"] == 1
    assert shown["findings"][0]["dismissed"]["note"] == "Возили груз, согласовано"
    module.restore_finding(finding["id"])
    assert finding["id"] in {f["id"] for f in module.month_review("2026-10")["findings"]}
    with pytest.raises(RecordValidationError):
        module.dismiss_finding("")


def test_print_settings_and_dismissals_do_not_wipe_each_other(module: PrimavtodorModule) -> None:
    module.settings.set_print_settings({"org_name": "ТЕСТ", "control": "mechanic"})
    module.dismiss_finding("X:1")
    module.settings.set_season("winter")

    assert module.settings.print_settings()["org_name"] == "ТЕСТ"
    assert "X:1" in module.settings.dismissed() and module.settings.season() == "winter"


def test_readiness_steps(module: PrimavtodorModule) -> None:
    vehicle, driver = car(module)
    make_waybill(module, driver, vehicle, number="1", date="2026-10-05")  # open
    review = module.month_review("2026-10")

    steps = {s["id"]: s for s in review["steps"]}
    assert steps["waybills"]["status"] == "warn" and "открыто 1" in steps["waybills"]["detail"]
    assert steps["fuel"]["status"] == "warn" and review["ready"] is False
    assert module.month_review("2026-09")["steps"][0]["status"] == "info"


def test_the_package_holds_everything(module: PrimavtodorModule) -> None:
    vehicle, driver = car(module)
    make_waybill(module, driver, vehicle, number="1", date="2026-10-05", season="summer",
                 odometer_out=0, odometer_in=100, fuel_out=40, fuel_in=20)  # fmt: skip

    content, name = module.month_package("2026-10")

    names = zipfile.ZipFile(io.BytesIO(content)).namelist()
    assert name == "Закрытие месяца 2026-10.zip"
    assert "Табель 2026-10.xlsx" in names and "Анализ расхода ГСМ 2026-10.xlsx" in names
    assert any(n.startswith("Карточки ГСМ/") for n in names) and "Замечания 2026-10.csv" in names
    assert "Расчёты по машинам 2026-10.csv" in names


@pytest.fixture
def client(tmp_path: Path):
    app = create_app(Settings(disk_dir=tmp_path / "disk"))
    with TestClient(app, base_url="http://127.0.0.1:8000") as test_client:
        yield test_client


def test_month_review_over_http(client: TestClient) -> None:
    vehicle = client.post("/api/primavtodor/records/vehicles",
                          json={"plate": "А1", "model": "Т", "norm_summer": 10}).json()  # fmt: skip
    driver = client.post("/api/primavtodor/records/employees",
                         json={"full_name": "Иванов Иван", "is_driver": True}).json()  # fmt: skip
    client.post("/api/primavtodor/records/waybills",
                json={"number": "1", "date": "2026-10-05", "driver_id": driver["id"],
                      "vehicle_id": vehicle["id"], "season": "summer", "odometer_out": 0,
                      "odometer_in": 100, "fuel_out": 40, "fuel_in": 20})  # fmt: skip

    review = client.get("/api/primavtodor/month/2026-10/review").json()
    finding = review["findings"][0]
    accepted = client.post("/api/primavtodor/findings/dismiss",
                           json={"id": finding["id"], "note": "ок"})
    restored = client.post("/api/primavtodor/findings/restore", json={"id": finding["id"]})
    package = client.get("/api/primavtodor/month/2026-10/package")
    bad = client.get("/api/primavtodor/month/октябрь/review")

    assert review["counts"]["error"] == 1 and finding["code"] == "OVERRUN"
    assert accepted.status_code == 200 and finding["id"] in accepted.json()["dismissed"]
    assert restored.json()["dismissed"] == {}
    assert package.headers["content-type"] == "application/zip" and package.content[:2] == b"PK"
    assert bad.status_code == 422

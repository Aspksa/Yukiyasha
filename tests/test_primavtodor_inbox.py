"""A statement dropped into «ГСМ/Входящие» is loaded; a clean file moves to «Обработано»."""

from pathlib import Path

import pytest

from tests.test_primavtodor_import import CARD, PETROL, prepare, statement_rows, xlsx
from yukiyasha.modules.disk import DiskModule
from yukiyasha.modules.primavtodor import PrimavtodorModule, fuel_inbox


@pytest.fixture
def setup(tmp_path: Path) -> tuple[DiskModule, PrimavtodorModule]:
    disk = DiskModule(tmp_path / "disk")
    disk.start()
    primavtodor = PrimavtodorModule(disk)
    primavtodor.start()
    return disk, primavtodor


def drop(disk: DiskModule, name: str, content: bytes) -> None:
    folder = disk.root / fuel_inbox.inbox_dir()
    (folder / name).write_bytes(content)


def test_the_folder_exists_and_is_empty(setup) -> None:
    _, module = setup
    assert module.fuel_inbox()["waiting"] == []
    assert module.fuel_inbox_scan() == {"files": [], "loaded": 0}


def test_dropped_statement_is_loaded_once_and_moved(setup) -> None:
    disk, module = setup
    prepare(module)
    rows = statement_rows((CARD, [("07.10.2026", "09:17:16", PETROL, 70.5, 40.0)]))
    drop(disk, "выписка.xlsx", xlsx(rows))
    drop(disk, "заметки.txt", b"not a statement")  # other files are left alone
    assert [f["name"] for f in module.fuel_inbox()["waiting"]] == ["выписка.xlsx"]

    result = module.fuel_inbox_scan()

    assert result["loaded"] == 1 and result["files"][0]["status"] == "loaded"
    assert len(module.data.snapshot("fuel")) == 1
    assert module.fuel_inbox()["waiting"] == []
    assert (disk.root / fuel_inbox.done_dir() / "выписка.xlsx").exists()

    drop(disk, "выписка.xlsx", xlsx(rows))  # the same file again: nothing is created twice
    again = module.fuel_inbox_scan()
    assert again["loaded"] == 0 and again["files"][0]["status"] == "loaded"
    assert len(module.data.snapshot("fuel")) == 1
    assert len(list((disk.root / fuel_inbox.done_dir()).iterdir())) == 2  # name was taken


def test_unmatched_operations_keep_the_file_in_the_inbox(setup) -> None:
    disk, module = setup
    prepare(module)
    rows = statement_rows(("7001000099990", [("07.10.2026", "09:00:00", PETROL, 70.0, 10.0)]))
    drop(disk, "чужая.xlsx", xlsx(rows))

    item = module.fuel_inbox_scan()["files"][0]

    assert item["status"] == "attention" and "7001000099990" in item["message"]
    assert [f["name"] for f in module.fuel_inbox()["waiting"]] == ["чужая.xlsx"]


def test_a_broken_file_does_not_stop_the_others(setup) -> None:
    disk, module = setup
    prepare(module)
    drop(disk, "a-сломан.xlsx", b"not a workbook")
    rows = statement_rows((CARD, [("07.10.2026", "09:17:16", PETROL, 70.5, 40.0)]))
    drop(disk, "b-хороший.xlsx", xlsx(rows))

    statuses = {f["name"]: f["status"] for f in module.fuel_inbox_scan()["files"]}

    assert statuses == {"a-сломан.xlsx": "failed", "b-хороший.xlsx": "loaded"}

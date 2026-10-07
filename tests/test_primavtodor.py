from pathlib import Path

import pytest

from yukiyasha.modules.disk import (
    DiskConflictError,
    DiskModule,
    DiskNotReadyError,
    DiskPathError,
)
from yukiyasha.modules.primavtodor import (
    PRIMAVTODOR_DIR,
    SECTIONS,
    SECTIONS_BY_ID,
    InvalidDocumentNameError,
    PrimavtodorModule,
    UnknownSectionError,
)
from yukiyasha.modules.registry import ModuleRegistry, ModuleState

EXPECTED_FOLDERS = [
    "Путевые листы",
    "Горюче-смазочные материалы",
    "Сотрудники",
    "Гараж",
    "Табель",
    "Договора",
    "Счёт-оферта",
    "Служебные записки",
    "Приказы",
    "Распоряжения",
]


def started(tmp_path: Path) -> tuple[DiskModule, PrimavtodorModule]:
    disk = DiskModule(tmp_path / "disk")
    module = PrimavtodorModule(disk)
    disk.start()
    module.start()
    return disk, module


def test_manifest_describes_the_module(tmp_path: Path) -> None:
    module = PrimavtodorModule(DiskModule(tmp_path / "disk"))

    assert module.manifest.module_id == "primavtodor"  # ASCII id; the display name is Russian
    assert module.manifest.name == "Примавтодор"
    assert module.manifest.permissions == ("disk.read", "disk.write", "disk.delete")
    assert module.directory == "projects/work/Примавтодор"


def test_sections_are_stable_and_unique() -> None:
    assert [section.folder for section in SECTIONS] == EXPECTED_FOLDERS
    assert len({section.id for section in SECTIONS}) == len(SECTIONS)
    assert all(section.id.isascii() and section.id.isidentifier() for section in SECTIONS)
    assert SECTIONS_BY_ID["fuel"].title == "Горюче-смазочные материалы"
    assert SECTIONS_BY_ID["timesheet"].path == "projects/work/Примавтодор/Табель"


def test_start_creates_the_project_and_every_section_folder(tmp_path: Path) -> None:
    disk = DiskModule(tmp_path / "disk")
    module = PrimavtodorModule(disk)
    disk.start()

    assert module.state is ModuleState.REGISTERED
    module.start()

    assert module.state is ModuleState.READY
    base = tmp_path / "disk" / "projects" / "work" / "Примавтодор"
    assert sorted(path.name for path in base.iterdir()) == sorted(EXPECTED_FOLDERS)
    assert "Примавтодор" in [entry["name"] for entry in disk.list_entries("projects/work")]


def test_start_is_idempotent_and_keeps_existing_files(tmp_path: Path) -> None:
    _, module = started(tmp_path)
    module.write_document("contracts", "договор-1.md", "важно")

    module.stop()
    module.start()

    assert module.read_document("contracts", "договор-1.md") == "важно"


def test_deleted_section_folder_is_recreated_on_start(tmp_path: Path) -> None:
    disk, module = started(tmp_path)
    disk.delete(SECTIONS_BY_ID["garage"].path)

    module.start()

    assert (tmp_path / "disk" / SECTIONS_BY_ID["garage"].path).is_dir()


def test_start_requires_a_ready_disk(tmp_path: Path) -> None:
    module = PrimavtodorModule(DiskModule(tmp_path / "disk"))  # disk never started

    with pytest.raises(DiskNotReadyError):
        module.start()
    assert module.state is ModuleState.REGISTERED


def test_a_file_in_the_way_is_reported_as_conflict(tmp_path: Path) -> None:
    disk = DiskModule(tmp_path / "disk")
    module = PrimavtodorModule(disk)
    disk.start()
    disk.write_text(f"{PRIMAVTODOR_DIR}/Табель", "i am a file")

    with pytest.raises(DiskConflictError):
        module.start()


def test_registry_marks_the_module_failed_and_rolls_back(tmp_path: Path) -> None:
    disk = DiskModule(tmp_path / "disk")
    module = PrimavtodorModule(disk)
    registry = ModuleRegistry()
    registry.register(disk)
    registry.register(module)
    (tmp_path / "disk" / "projects" / "work").mkdir(parents=True)
    (tmp_path / "disk" / "projects" / "work" / "Примавтодор").write_text("blocker")

    with pytest.raises(DiskConflictError):
        registry.start_all()

    assert module.state is ModuleState.FAILED
    assert disk.state is ModuleState.STOPPED
    health = module.snapshot()["health"]
    assert health["status"] == "failed" and "error" in health


def test_snapshot_reports_folder_and_section_count(tmp_path: Path) -> None:
    _, module = started(tmp_path)

    snapshot = module.snapshot()

    assert snapshot["state"] == "ready"
    assert snapshot["health"] == {
        "status": "ok",
        "directory": "projects/work/Примавтодор",
        "sections": 10,
    }


def test_section_summaries_count_what_is_on_the_disk(tmp_path: Path) -> None:
    _, module = started(tmp_path)
    module.write_document("orders", "приказ-1.md", "а")
    module.write_document("orders", "приказ-2.md", "б")
    module.write_document("fuel", "март.csv", "в")

    summaries = {item["id"]: item for item in module.section_summaries()}

    assert list(summaries) == [section.id for section in SECTIONS]
    assert summaries["orders"]["count"] == 2
    assert summaries["fuel"]["count"] == 1
    assert summaries["timesheet"]["count"] == 0
    assert summaries["orders"]["path"] == "projects/work/Примавтодор/Приказы"
    assert summaries["orders"]["group_title"] == "Документы"
    assert summaries["garage"]["group_title"] == "Учёт"


def test_document_roundtrip_in_a_section(tmp_path: Path) -> None:
    disk, module = started(tmp_path)

    path = module.write_document("memos", "записка 1.md", "Прошу выделить автомобиль.")

    assert path == "projects/work/Примавтодор/Служебные записки/записка 1.md"
    assert disk.read_text(path) == "Прошу выделить автомобиль."  # really stored on the disk
    assert module.read_document("memos", "записка 1.md") == "Прошу выделить автомобиль."
    assert [entry["name"] for entry in module.list_documents("memos")] == ["записка 1.md"]

    module.delete_document("memos", "записка 1.md")
    assert module.list_documents("memos") == []


def test_write_document_respects_overwrite_flag(tmp_path: Path) -> None:
    _, module = started(tmp_path)
    module.write_document("contracts", "a.md", "1")

    with pytest.raises(DiskConflictError):
        module.write_document("contracts", "a.md", "2", overwrite=False)
    module.write_document("contracts", "a.md", "3")

    assert module.read_document("contracts", "a.md") == "3"


def test_unknown_section_is_rejected(tmp_path: Path) -> None:
    _, module = started(tmp_path)

    with pytest.raises(UnknownSectionError):
        module.list_documents("../etc")
    with pytest.raises(UnknownSectionError):
        module.write_document("nope", "a.md", "x")


@pytest.mark.parametrize("name", ["", "   ", ".", "..", "a/b.md", "..\\x.md", "sub/../x"])
def test_document_name_must_be_a_single_plain_file_name(tmp_path: Path, name: str) -> None:
    disk, module = started(tmp_path)

    with pytest.raises(InvalidDocumentNameError):
        module.write_document("orders", name, "x")
    assert disk.list_entries(SECTIONS_BY_ID["orders"].path) == []


def test_disk_validation_still_applies_to_document_names(tmp_path: Path) -> None:
    _, module = started(tmp_path)

    with pytest.raises(DiskPathError):
        module.write_document("orders", "bad:name.md", "x")
    with pytest.raises(DiskPathError):
        module.write_document("orders", "CON.txt", "x")



def test_document_summaries_and_preview_are_limited_to_document_sections(tmp_path: Path) -> None:
    _, module = started(tmp_path)
    content = "Служебная записка\nПрошу выделить автомобиль для выезда.\nСрок: сегодня."
    module.write_document("memos", "записка-12.md", content)

    summaries = module.document_summaries("memos")
    preview = module.document_preview("memos", "записка-12.md", max_chars=40)

    assert summaries == [
        {
            "section_id": "memos",
            "section_title": "Служебные записки",
            "name": "записка-12.md",
            "path": "projects/work/Примавтодор/Служебные записки/записка-12.md",
            "size": len(content.encode("utf-8")),
            "extension": "md",
        }
    ]
    assert preview["section_id"] == "memos"
    assert preview["section_title"] == "Служебные записки"
    assert preview["name"] == "записка-12.md"
    assert preview["preview"].startswith("Служебная записка Прошу")
    assert preview["truncated"] is True

    with pytest.raises(UnknownSectionError):
        module.document_summaries("fuel")
    with pytest.raises(UnknownSectionError):
        module.document_preview("waybills", "anything.txt")

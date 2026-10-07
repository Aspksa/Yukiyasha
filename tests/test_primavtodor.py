from pathlib import Path

import pytest

from yukiyasha.modules.disk import DiskConflictError, DiskModule, DiskNotReadyError
from yukiyasha.modules.primavtodor import PRIMAVTODOR_DIR, PrimavtodorModule
from yukiyasha.modules.registry import ModuleRegistry, ModuleState


def make_pair(tmp_path: Path) -> tuple[DiskModule, PrimavtodorModule]:
    disk = DiskModule(tmp_path / "disk")
    return disk, PrimavtodorModule(disk)


def test_manifest_describes_the_module(tmp_path: Path) -> None:
    _, module = make_pair(tmp_path)

    assert module.manifest.module_id == "primavtodor"  # ASCII id; the display name is Russian
    assert module.manifest.name == "Примавтодор"
    assert module.manifest.permissions == ("disk.read", "disk.write")
    assert module.directory == "projects/work/Примавтодор"


def test_start_creates_the_project_folder_in_the_work_section(tmp_path: Path) -> None:
    disk, module = make_pair(tmp_path)
    disk.start()

    assert module.state is ModuleState.REGISTERED
    module.start()

    assert module.state is ModuleState.READY
    assert (tmp_path / "disk" / "projects" / "work" / "Примавтодор").is_dir()
    names = [entry["name"] for entry in disk.list_entries("projects/work")]
    assert "Примавтодор" in names


def test_start_is_idempotent_and_keeps_existing_files(tmp_path: Path) -> None:
    disk, module = make_pair(tmp_path)
    disk.start()
    module.start()
    disk.write_text(f"{PRIMAVTODOR_DIR}/заметка.md", "важно")

    module.stop()
    module.start()

    assert disk.read_text(f"{PRIMAVTODOR_DIR}/заметка.md") == "важно"


def test_folder_is_recreated_if_the_user_deleted_it(tmp_path: Path) -> None:
    disk, module = make_pair(tmp_path)
    disk.start()
    module.start()
    disk.delete(PRIMAVTODOR_DIR)

    module.start()

    assert (tmp_path / "disk" / "projects" / "work" / "Примавтодор").is_dir()


def test_start_requires_a_ready_disk(tmp_path: Path) -> None:
    _, module = make_pair(tmp_path)  # disk never started

    with pytest.raises(DiskNotReadyError):
        module.start()
    assert module.state is ModuleState.REGISTERED


def test_a_file_in_the_way_is_reported_as_conflict(tmp_path: Path) -> None:
    disk, module = make_pair(tmp_path)
    disk.start()
    disk.write_text(PRIMAVTODOR_DIR, "i am a file")

    with pytest.raises(DiskConflictError):
        module.start()


def test_registry_marks_the_module_failed_and_rolls_back(tmp_path: Path) -> None:
    disk, module = make_pair(tmp_path)
    registry = ModuleRegistry()
    registry.register(disk)
    registry.register(module)
    (tmp_path / "disk" / "projects" / "work").mkdir(parents=True)
    (tmp_path / "disk" / "projects" / "work" / "Примавтодор").write_text("blocker")

    with pytest.raises(DiskConflictError):
        registry.start_all()

    assert module.state is ModuleState.FAILED
    assert disk.state is ModuleState.STOPPED
    snapshot = module.snapshot()
    assert snapshot["health"]["status"] == "failed"
    assert "error" in snapshot["health"]


def test_snapshot_reports_the_folder(tmp_path: Path) -> None:
    disk, module = make_pair(tmp_path)
    disk.start()
    module.start()

    snapshot = module.snapshot()

    assert snapshot["state"] == "ready"
    assert snapshot["health"] == {"status": "ok", "directory": "projects/work/Примавтодор"}
    assert snapshot["manifest"]["name"] == "Примавтодор"

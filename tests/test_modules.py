from pathlib import Path

import pytest

from yukiyasha.modules.disk import DiskModule, DiskSecurityError
from yukiyasha.modules.registry import ModuleRegistry, ModuleState


def test_disk_lifecycle_and_manifest(tmp_path: Path) -> None:
    disk = DiskModule(tmp_path / "disk")
    registry = ModuleRegistry()
    registry.register(disk)

    assert disk.state is ModuleState.REGISTERED

    registry.start_all()

    assert disk.state is ModuleState.READY
    assert disk.root.exists()
    snapshot = registry.snapshots()[0]
    assert snapshot["manifest"]["module_id"] == "disk"
    assert snapshot["manifest"]["name"] == "Диск Yukiyasha"
    assert snapshot["health"]["status"] == "ok"

    registry.stop_all()
    assert disk.state is ModuleState.STOPPED


def test_registry_rejects_duplicate_module(tmp_path: Path) -> None:
    registry = ModuleRegistry()
    registry.register(DiskModule(tmp_path / "one"))

    with pytest.raises(ValueError, match="already registered"):
        registry.register(DiskModule(tmp_path / "two"))


def test_disk_write_read_list_delete(tmp_path: Path) -> None:
    disk = DiskModule(tmp_path / "disk")
    disk.start()

    disk.write_text("notes/hello.txt", "Привет, Yukiyasha")

    assert disk.read_text("notes/hello.txt") == "Привет, Yukiyasha"
    entries = disk.list_entries("notes")
    assert entries == [
        {
            "name": "hello.txt",
            "path": "notes/hello.txt",
            "type": "file",
            "size": len("Привет, Yukiyasha".encode("utf-8")),
        }
    ]

    disk.delete("notes/hello.txt")
    assert disk.list_entries("notes") == []


def test_disk_blocks_path_traversal(tmp_path: Path) -> None:
    disk = DiskModule(tmp_path / "disk")
    disk.start()

    with pytest.raises(DiskSecurityError):
        disk.write_text("../escape.txt", "blocked")

    with pytest.raises(DiskSecurityError):
        disk.read_text("../escape.txt")


def test_disk_respects_overwrite_flag(tmp_path: Path) -> None:
    disk = DiskModule(tmp_path / "disk")
    disk.start()
    disk.write_text("file.txt", "first")

    with pytest.raises(FileExistsError):
        disk.write_text("file.txt", "second", overwrite=False)

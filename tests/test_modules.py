import errno
import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from yukiyasha.modules.disk import (
    DiskConflictError,
    DiskDirectoryNotEmptyError,
    DiskEncodingError,
    DiskError,
    DiskModule,
    DiskPathError,
    DiskSecurityError,
    DiskTooLargeError,
)
from yukiyasha.modules.manifest import ModuleManifest
from yukiyasha.modules.registry import ModuleRegistry, ModuleState


@dataclass
class FakeModule:
    module_id: str
    fail_start: bool = False
    fail_stop: bool = False

    def __post_init__(self) -> None:
        self.manifest = ModuleManifest(
            module_id=self.module_id,
            name=self.module_id,
            version="test",
            description="test module",
            permissions=(),
        )
        self._state = ModuleState.REGISTERED
        self.stop_calls = 0

    @property
    def state(self) -> ModuleState:
        return self._state

    def start(self) -> None:
        if self.fail_start:
            raise RuntimeError(f"{self.module_id} start failed")
        self._state = ModuleState.READY

    def stop(self) -> None:
        self.stop_calls += 1
        self._state = ModuleState.STOPPED
        if self.fail_stop:
            raise RuntimeError(f"{self.module_id} stop failed")

    def fail(self, error: BaseException) -> None:
        self._state = ModuleState.FAILED

    def snapshot(self) -> dict[str, object]:
        return {"state": self.state.value}


def test_disk_lifecycle_and_manifest(tmp_path: Path) -> None:
    disk = DiskModule(tmp_path / "disk")
    registry = ModuleRegistry()
    registry.register(disk)

    assert disk.state is ModuleState.REGISTERED

    registry.start_all()

    assert disk.state is ModuleState.READY
    assert disk.root.exists()
    assert (disk.root / "projects" / "work").is_dir()
    assert (disk.root / "projects" / "home").is_dir()
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


@pytest.mark.parametrize("module_id", ["", "../bad", "bad id", "bad/slash"])
def test_registry_rejects_invalid_module_id(module_id: str) -> None:
    registry = ModuleRegistry()

    with pytest.raises(ValueError, match="Invalid module id"):
        registry.register(FakeModule(module_id))


def test_registry_rolls_back_and_marks_failed_module() -> None:
    first = FakeModule("first")
    broken = FakeModule("broken", fail_start=True)
    registry = ModuleRegistry()
    registry.register(first)
    registry.register(broken)

    with pytest.raises(RuntimeError, match="start failed"):
        registry.start_all()

    assert first.state is ModuleState.STOPPED
    assert broken.state is ModuleState.FAILED
    assert broken.stop_calls == 1


def test_registry_stop_all_continues_after_errors() -> None:
    first = FakeModule("first", fail_stop=True)
    second = FakeModule("second", fail_stop=True)
    registry = ModuleRegistry()
    registry.register(first)
    registry.register(second)
    first.start()
    second.start()

    with pytest.raises(ExceptionGroup) as caught:
        registry.stop_all()

    assert len(caught.value.exceptions) == 2
    assert first.stop_calls == 1
    assert second.stop_calls == 1


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
            "size": len("Привет, Yukiyasha".encode()),
        }
    ]

    disk.delete("notes/hello.txt")
    assert disk.list_entries("notes") == []


def test_disk_preserves_newlines_exactly(tmp_path: Path) -> None:
    disk = DiskModule(tmp_path / "disk")
    disk.start()
    content = "a\r\nb\nc"

    disk.write_text("line-endings.txt", content)

    assert (disk.root / "line-endings.txt").read_bytes() == content.encode()
    assert disk.read_text("line-endings.txt") == content


def test_disk_blocks_path_traversal(tmp_path: Path) -> None:
    disk = DiskModule(tmp_path / "disk")
    disk.start()

    with pytest.raises(DiskSecurityError):
        disk.write_text("../escape.txt", "blocked")

    with pytest.raises(DiskSecurityError):
        disk.read_text("../escape.txt")


def test_disk_blocks_symlink_escape(tmp_path: Path) -> None:
    disk = DiskModule(tmp_path / "disk")
    disk.start()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = disk.root / "escape"

    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Symlink creation is unavailable on this platform")

    with pytest.raises(DiskSecurityError):
        disk.write_text("escape/file.txt", "blocked")

    assert not (outside / "file.txt").exists()


def test_disk_no_overwrite_is_race_safe_semantics(tmp_path: Path) -> None:
    disk = DiskModule(tmp_path / "disk")
    disk.start()
    disk.write_text("file.txt", "first")

    with pytest.raises(DiskConflictError, match="already exists"):
        disk.write_text("file.txt", "second", overwrite=False)

    assert disk.read_text("file.txt") == "first"


def test_disk_atomic_overwrite_preserves_original_on_publish_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    disk = DiskModule(tmp_path / "disk")
    disk.start()
    disk.write_text("file.txt", "original")

    def fail_replace(
        source: str | bytes | os.PathLike[str],
        target: str | bytes | os.PathLike[str],
    ) -> None:
        raise OSError(errno.EIO, "simulated publish failure")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(DiskError):
        disk.write_text("file.txt", "replacement")

    assert disk.read_text("file.txt") == "original"
    assert not list(disk.root.glob(".yukiyasha-*"))


def test_disk_parent_file_conflict(tmp_path: Path) -> None:
    disk = DiskModule(tmp_path / "disk")
    disk.start()
    disk.write_text("a.txt", "file")

    with pytest.raises(DiskConflictError, match="Parent path"):
        disk.write_text("a.txt/b.txt", "blocked")


def test_disk_rejects_surrogate_text(tmp_path: Path) -> None:
    disk = DiskModule(tmp_path / "disk")
    disk.start()

    with pytest.raises(DiskEncodingError, match="valid UTF-8"):
        disk.write_text("bad.txt", "\ud800")


def test_disk_rejects_too_large_text(tmp_path: Path) -> None:
    disk = DiskModule(tmp_path / "disk")
    disk.start()

    with pytest.raises(DiskTooLargeError):
        disk.write_text("big.txt", "x" * (1_048_576 + 1))


def test_disk_rejects_too_long_filename(tmp_path: Path) -> None:
    disk = DiskModule(tmp_path / "disk")
    disk.start()

    with pytest.raises(DiskPathError):
        disk.write_text("x" * 300, "blocked")


def test_disk_delete_non_empty_directory(tmp_path: Path) -> None:
    disk = DiskModule(tmp_path / "disk")
    disk.start()
    disk.write_text("folder/file.txt", "data")

    with pytest.raises(DiskDirectoryNotEmptyError):
        disk.delete("folder")

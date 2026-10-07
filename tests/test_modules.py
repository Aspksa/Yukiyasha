import errno
import os
import stat
from dataclasses import dataclass
from pathlib import Path

import pytest

from yukiyasha.modules.disk import (
    DiskConflictError,
    DiskDirectoryNotEmptyError,
    DiskEncodingError,
    DiskError,
    DiskModule,
    DiskNotReadyError,
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


@pytest.mark.parametrize("module_id", ["", "../bad", "bad id", "bad/slash", "диск", "disk\u0661"])
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


def test_disk_rejects_operations_outside_ready_state(tmp_path: Path) -> None:
    disk = DiskModule(tmp_path / "disk")

    with pytest.raises(DiskNotReadyError):
        disk.list_entries()

    disk.start()
    disk.stop()

    with pytest.raises(DiskNotReadyError):
        disk.read_text("anything.txt")


@pytest.mark.parametrize(
    "path",
    [
        "a\x00b.txt",
        "a:b.txt",
        "CON",
        "nul.txt",
        "COM1.log",
        "name.",
        "name ",
        "folder\\file.txt",
    ],
)
def test_disk_rejects_nonportable_windows_paths(tmp_path: Path, path: str) -> None:
    disk = DiskModule(tmp_path / "disk")
    disk.start()

    with pytest.raises(DiskPathError):
        disk.write_text(path, "blocked")


def test_disk_rejects_internal_symlink_target(tmp_path: Path) -> None:
    disk = DiskModule(tmp_path / "disk")
    disk.start()
    disk.write_text("a.txt", "original")
    link = disk.root / "ln"

    try:
        link.symlink_to(disk.root / "a.txt")
    except OSError:
        pytest.skip("Symlink creation is unavailable on this platform")

    with pytest.raises(DiskSecurityError, match="Symlinks"):
        disk.delete("ln")

    assert (disk.root / "a.txt").read_text() == "original"
    assert link.is_symlink()


def test_disk_no_overwrite_falls_back_when_hardlinks_unsupported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    disk = DiskModule(tmp_path / "disk")
    disk.start()

    def unsupported_link(*args, **kwargs) -> None:
        raise OSError(errno.EPERM, "hard links unsupported")

    monkeypatch.setattr(os, "link", unsupported_link)
    disk.write_text("fallback.txt", "content", overwrite=False)

    assert disk.read_text("fallback.txt") == "content"
    assert not list(disk.root.glob(".yukiyasha-*"))


@pytest.mark.parametrize("path", ["projects", "projects/work", "projects/home"])
def test_disk_protects_builtin_project_directories(tmp_path: Path, path: str) -> None:
    disk = DiskModule(tmp_path / "disk")
    disk.start()

    with pytest.raises(DiskSecurityError, match="cannot be deleted"):
        disk.delete(path)


def test_disk_hides_and_cleans_stale_temp_files(tmp_path: Path) -> None:
    root = tmp_path / "disk"
    root.mkdir()
    stale = root / ".yukiyasha-ab12cd34"
    stale.write_text("partial")

    disk = DiskModule(root)
    disk.start()

    assert not stale.exists()
    live_temp = root / ".yukiyasha-ef56gh78"
    live_temp.write_text("partial")
    assert all(entry["name"] != live_temp.name for entry in disk.list_entries())


def test_disk_keeps_user_files_that_only_share_the_temp_prefix(tmp_path: Path) -> None:
    disk = DiskModule(tmp_path / "disk")
    disk.start()

    disk.write_text(".yukiyasha-notes.txt", "mine")
    disk.stop()
    disk.start()  # startup cleanup must not touch it

    assert disk.read_text(".yukiyasha-notes.txt") == "mine"
    assert ".yukiyasha-notes.txt" in [entry["name"] for entry in disk.list_entries()]


def test_disk_rejects_names_reserved_for_temp_files(tmp_path: Path) -> None:
    disk = DiskModule(tmp_path / "disk")
    disk.start()

    with pytest.raises(DiskPathError, match="temporary"):
        disk.write_text("sub/.yukiyasha-ab12cd34", "x")


def test_disk_protects_builtin_directories_by_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A differently-spelled path to the same directory (case-insensitive FS) stays protected."""
    disk = DiskModule(tmp_path / "disk")
    disk.start()
    real = (tmp_path / "disk" / "projects" / "work").resolve()
    # Simulate "projects/WORK" resolving to the real directory, as on NTFS or APFS.
    monkeypatch.setattr(disk, "_resolve", lambda _path: real)

    with pytest.raises(DiskSecurityError, match="cannot be deleted"):
        disk.delete("projects/WORK")
    assert real.is_dir()


def test_disk_overwrite_preserves_file_mode(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("POSIX permission bits")
    disk = DiskModule(tmp_path / "disk")
    disk.start()
    disk.write_text("script.sh", "one")
    target = tmp_path / "disk" / "script.sh"
    target.chmod(0o644)

    disk.write_text("script.sh", "two")

    assert stat.S_IMODE(target.stat().st_mode) == 0o644
    assert disk.read_text("script.sh") == "two"


def test_disk_rejects_paths_whose_real_target_escapes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """NTFS junctions are not symlinks; the fully resolved path must still stay inside."""
    disk = DiskModule(tmp_path / "disk")
    disk.start()
    outside = tmp_path / "outside"
    outside.mkdir()
    original = os.path.realpath

    def fake_realpath(path, *args, **kwargs):
        if str(path).endswith("junction"):
            return str(outside)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(os.path, "realpath", fake_realpath)

    with pytest.raises(DiskSecurityError, match="escapes"):
        disk.list_entries("junction")


def test_disk_make_dir_creates_nested_directories_idempotently(tmp_path: Path) -> None:
    disk = DiskModule(tmp_path / "disk")
    disk.start()

    disk.make_dir("a/b/c")
    disk.make_dir("a/b/c")  # second call is a no-op
    disk.make_dir("")  # the root already exists

    assert (tmp_path / "disk" / "a" / "b" / "c").is_dir()
    assert [entry["name"] for entry in disk.list_entries("a/b")] == ["c"]


def test_disk_make_dir_rejects_conflicts_traversal_and_not_ready(tmp_path: Path) -> None:
    disk = DiskModule(tmp_path / "disk")
    with pytest.raises(DiskNotReadyError):
        disk.make_dir("x")

    disk.start()
    disk.write_text("file.txt", "x")
    with pytest.raises(DiskConflictError):
        disk.make_dir("file.txt")
    with pytest.raises(DiskConflictError):
        disk.make_dir("file.txt/sub")
    with pytest.raises(DiskSecurityError):
        disk.make_dir("../outside")
    with pytest.raises(DiskPathError):
        disk.make_dir("bad:name")
    assert not (tmp_path / "outside").exists()

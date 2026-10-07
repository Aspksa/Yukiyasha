"""Binary reads and moves used by the statement inbox."""

import pytest

from yukiyasha.modules.disk import DiskConflictError, DiskModule, DiskSecurityError


def test_read_bytes_and_move_stay_inside_the_disk(tmp_path) -> None:
    disk = DiskModule(tmp_path / "disk")
    disk.start()
    (disk.root / "projects" / "work" / "a.bin").write_bytes(b"\x00\xff data")

    assert disk.read_bytes("projects/work/a.bin") == b"\x00\xff data"
    disk.move("projects/work/a.bin", "projects/work/sub/b.bin")
    assert (disk.root / "projects/work/sub/b.bin").exists()
    with pytest.raises(FileNotFoundError):
        disk.read_bytes("projects/work/a.bin")
    disk.write_text("projects/work/c.txt", "x")
    with pytest.raises(DiskConflictError):
        disk.move("projects/work/c.txt", "projects/work/sub/b.bin")  # never overwrites
    with pytest.raises(DiskSecurityError):
        disk.move("projects/work/c.txt", "../outside.txt")

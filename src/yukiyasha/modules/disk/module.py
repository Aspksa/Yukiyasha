"""Sandboxed local storage module for Yukiyasha."""

from pathlib import Path

from yukiyasha.modules.manifest import ModuleManifest
from yukiyasha.modules.registry import ModuleState

MAX_TEXT_BYTES = 1_048_576

DISK_MANIFEST = ModuleManifest(
    module_id="disk",
    name="Диск Yukiyasha",
    version="0.2.0",
    description="Локальное sandbox-хранилище файлов Yukiyasha.",
    permissions=("disk.read", "disk.write", "disk.delete"),
)


class DiskSecurityError(ValueError):
    """Raised when a path attempts to escape the disk sandbox."""


class DiskModule:
    manifest = DISK_MANIFEST

    def __init__(self, root: Path) -> None:
        self.root = root
        self._state = ModuleState.REGISTERED

    @property
    def state(self) -> ModuleState:
        return self._state

    def start(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._state = ModuleState.READY

    def stop(self) -> None:
        self._state = ModuleState.STOPPED

    def snapshot(self) -> dict[str, object]:
        return {
            "manifest": self.manifest.to_dict(),
            "state": self.state.value,
            "health": {
                "status": "ok" if self.state is ModuleState.READY else self.state.value,
                "root": str(self.root),
            },
        }

    def list_entries(self, relative_path: str = "") -> list[dict[str, object]]:
        directory = self._resolve(relative_path)
        if not directory.exists():
            raise FileNotFoundError(relative_path)
        if not directory.is_dir():
            raise NotADirectoryError(relative_path)

        entries: list[dict[str, object]] = []
        for item in sorted(directory.iterdir(), key=lambda value: (not value.is_dir(), value.name.lower())):
            if item.is_symlink():
                continue
            stat = item.stat()
            entries.append(
                {
                    "name": item.name,
                    "path": item.relative_to(self.root.resolve()).as_posix(),
                    "type": "directory" if item.is_dir() else "file",
                    "size": 0 if item.is_dir() else stat.st_size,
                }
            )
        return entries

    def read_text(self, relative_path: str) -> str:
        path = self._resolve(relative_path)
        if not path.exists():
            raise FileNotFoundError(relative_path)
        if not path.is_file():
            raise IsADirectoryError(relative_path)
        if path.stat().st_size > MAX_TEXT_BYTES:
            raise ValueError("File is too large to read as text")
        return path.read_text(encoding="utf-8")

    def write_text(self, relative_path: str, content: str, *, overwrite: bool = True) -> None:
        encoded = content.encode("utf-8")
        if len(encoded) > MAX_TEXT_BYTES:
            raise ValueError("File is too large to write as text")

        path = self._resolve(relative_path)
        if path == self.root.resolve():
            raise DiskSecurityError("A file path is required")
        if path.exists() and path.is_dir():
            raise IsADirectoryError(relative_path)
        if path.exists() and not overwrite:
            raise FileExistsError(relative_path)

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def delete(self, relative_path: str) -> None:
        path = self._resolve(relative_path)
        if path == self.root.resolve():
            raise DiskSecurityError("The disk root cannot be deleted")
        if not path.exists():
            raise FileNotFoundError(relative_path)
        if path.is_dir():
            path.rmdir()
        else:
            path.unlink()

    def _resolve(self, relative_path: str) -> Path:
        raw = Path(relative_path)
        if raw.is_absolute():
            raise DiskSecurityError("Absolute paths are not allowed")

        root = self.root.resolve()
        candidate = (root / raw).resolve()
        if not candidate.is_relative_to(root):
            raise DiskSecurityError("Path escapes Yukiyasha Disk")
        return candidate

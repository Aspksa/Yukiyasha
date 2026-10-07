"""Sandboxed local storage module for Yukiyasha."""

import errno
import os
import tempfile
from pathlib import Path

from yukiyasha.modules.manifest import ModuleManifest
from yukiyasha.modules.registry import ModuleState
from yukiyasha.version import get_version

MAX_TEXT_BYTES = 1_048_576

DISK_MANIFEST = ModuleManifest(
    module_id="disk",
    name="Диск Yukiyasha",
    version=get_version(),
    description="Локальное sandbox-хранилище файлов Yukiyasha.",
    permissions=("disk.read", "disk.write", "disk.delete"),
)


class DiskError(Exception):
    """Base class for expected disk-domain errors."""


class DiskSecurityError(DiskError):
    """Raised when a path attempts to escape the disk sandbox."""


class DiskPathError(DiskError):
    """Raised when a filesystem path is invalid for the host OS."""


class DiskConflictError(DiskError):
    """Raised when an operation conflicts with an existing filesystem entry."""


class DiskEncodingError(DiskError):
    """Raised when text cannot be represented as valid UTF-8."""


class DiskTooLargeError(DiskError):
    """Raised when text exceeds the configured API size limit."""


class DiskPermissionError(DiskError):
    """Raised when the OS denies access to a filesystem entry."""


class DiskDirectoryNotEmptyError(DiskConflictError):
    """Raised when attempting to remove a non-empty directory."""


class DiskModule:
    manifest = DISK_MANIFEST

    def __init__(self, root: Path) -> None:
        self.root = root
        self._state = ModuleState.REGISTERED
        self._last_error: str | None = None

    @property
    def state(self) -> ModuleState:
        return self._state

    def start(self) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            (self.root / "projects" / "work").mkdir(parents=True, exist_ok=True)
            (self.root / "projects" / "home").mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise self._translate_os_error(exc) from exc
        self._last_error = None
        self._state = ModuleState.READY

    def stop(self) -> None:
        self._state = ModuleState.STOPPED

    def fail(self, error: BaseException) -> None:
        self._last_error = str(error)
        self._state = ModuleState.FAILED

    def snapshot(self) -> dict[str, object]:
        health: dict[str, object] = {
            "status": "ok" if self.state is ModuleState.READY else self.state.value,
            "root": str(self.root),
        }
        if self._last_error:
            health["error"] = self._last_error
        return {
            "manifest": self.manifest.to_dict(),
            "state": self.state.value,
            "health": health,
        }

    def list_entries(self, relative_path: str = "") -> list[dict[str, object]]:
        directory = self._resolve(relative_path)
        try:
            if not directory.exists():
                raise FileNotFoundError(relative_path)
            if not directory.is_dir():
                raise NotADirectoryError(relative_path)
        except (FileNotFoundError, NotADirectoryError):
            raise
        except OSError as exc:
            raise self._translate_os_error(exc) from exc

        try:
            visible = [item for item in directory.iterdir() if not item.is_symlink()]
            visible.sort(key=lambda value: (not value.is_dir(), value.name.lower()))
            entries: list[dict[str, object]] = []
            root = self.root.resolve()
            for item in visible:
                stat = item.stat()
                entries.append(
                    {
                        "name": item.name,
                        "path": item.relative_to(root).as_posix(),
                        "type": "directory" if item.is_dir() else "file",
                        "size": 0 if item.is_dir() else stat.st_size,
                    }
                )
            return entries
        except OSError as exc:
            raise self._translate_os_error(exc) from exc

    def read_text(self, relative_path: str) -> str:
        path = self._resolve(relative_path)
        try:
            if not path.exists():
                raise FileNotFoundError(relative_path)
            if not path.is_file():
                raise IsADirectoryError(relative_path)
        except (FileNotFoundError, IsADirectoryError):
            raise
        except OSError as exc:
            raise self._translate_os_error(exc) from exc

        try:
            with path.open("rb") as handle:
                payload = handle.read(MAX_TEXT_BYTES + 1)
        except OSError as exc:
            raise self._translate_os_error(exc) from exc

        if len(payload) > MAX_TEXT_BYTES:
            raise DiskTooLargeError("Text file exceeds the 1 MiB limit")
        try:
            return payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DiskEncodingError("File is not valid UTF-8 text") from exc

    def write_text(self, relative_path: str, content: str, *, overwrite: bool = True) -> None:
        try:
            encoded = content.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise DiskEncodingError("Content must be valid UTF-8 text") from exc
        if len(encoded) > MAX_TEXT_BYTES:
            raise DiskTooLargeError("Text content exceeds the 1 MiB limit")

        path = self._resolve(relative_path)
        if path == self.root.resolve():
            raise DiskPathError("A file path is required")

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except (FileExistsError, NotADirectoryError) as exc:
            raise DiskConflictError("Parent path is not a directory") from exc
        except OSError as exc:
            raise self._translate_os_error(exc) from exc

        try:
            if path.exists() and path.is_dir():
                raise DiskConflictError("Target path is a directory")
            if path.is_symlink():
                raise DiskSecurityError("Writing through symlinks is not allowed")
        except DiskError:
            raise
        except OSError as exc:
            raise self._translate_os_error(exc) from exc

        temp_path: Path | None = None
        try:
            fd, raw_temp_path = tempfile.mkstemp(prefix=".yukiyasha-", dir=path.parent)
            temp_path = Path(raw_temp_path)
            with os.fdopen(fd, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())

            if overwrite:
                os.replace(temp_path, path)
            else:
                try:
                    os.link(temp_path, path)
                except FileExistsError as exc:
                    raise DiskConflictError("File already exists") from exc
                temp_path.unlink()
                temp_path = None
        except DiskError:
            raise
        except OSError as exc:
            raise self._translate_os_error(exc) from exc
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def delete(self, relative_path: str) -> None:
        path = self._resolve(relative_path)
        if path == self.root.resolve():
            raise DiskSecurityError("The disk root cannot be deleted")
        try:
            if not path.exists():
                raise FileNotFoundError(relative_path)
            if path.is_symlink():
                raise DiskSecurityError("Deleting symlinks is not allowed")
        except (FileNotFoundError, DiskSecurityError):
            raise
        except OSError as exc:
            raise self._translate_os_error(exc) from exc

        try:
            if path.is_dir():
                path.rmdir()
            else:
                path.unlink()
        except OSError as exc:
            if exc.errno == errno.ENOTEMPTY:
                raise DiskDirectoryNotEmptyError("Directory is not empty") from exc
            raise self._translate_os_error(exc) from exc

    def _resolve(self, relative_path: str) -> Path:
        raw = Path(relative_path)
        if raw.is_absolute():
            raise DiskSecurityError("Absolute paths are not allowed")

        try:
            root = self.root.resolve()
            candidate = (root / raw).resolve()
        except OSError as exc:
            raise self._translate_os_error(exc) from exc

        if not candidate.is_relative_to(root):
            raise DiskSecurityError("Path escapes Yukiyasha Disk")
        return candidate

    @staticmethod
    def _translate_os_error(exc: OSError) -> DiskError:
        if isinstance(exc, PermissionError) or exc.errno in {errno.EACCES, errno.EPERM}:
            return DiskPermissionError("Filesystem permission denied")
        if exc.errno in {errno.ENAMETOOLONG, errno.EINVAL}:
            return DiskPathError("Invalid filesystem path")
        if exc.errno == errno.ENOTDIR:
            return DiskConflictError("Parent path is not a directory")
        return DiskError(f"Filesystem operation failed: {exc.strerror or exc.__class__.__name__}")

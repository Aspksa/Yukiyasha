"""Permission-checked and path-scoped access to Yukiyasha Disk for modules."""

from pathlib import PurePosixPath

from yukiyasha.modules.disk.module import DiskModule
from yukiyasha.modules.permissions import PermissionBroker, PermissionDeniedError


class DiskAccess:
    """Expose only disk operations and path roots granted to a module."""

    def __init__(
        self,
        disk: DiskModule,
        broker: PermissionBroker,
        subject: str,
        *,
        roots: tuple[str, ...],
    ) -> None:
        self._disk = disk
        self._broker = broker
        self._subject = subject
        self._roots = tuple(root.strip("/") for root in roots)

    @property
    def state(self):
        return self._disk.state

    def _require_path(self, relative_path: str) -> None:
        candidate = PurePosixPath(relative_path).as_posix().strip("/")
        for root in self._roots:
            if candidate == root or candidate.startswith(f"{root}/"):
                return
        raise PermissionDeniedError(
            f"Module {self._subject!r} cannot access disk path {relative_path!r}"
        )

    def list_entries(self, relative_path: str = "") -> list[dict[str, object]]:
        self._broker.require(self._subject, "disk.read")
        self._require_path(relative_path)
        return self._disk.list_entries(relative_path)

    def read_text(self, relative_path: str) -> str:
        self._broker.require(self._subject, "disk.read")
        self._require_path(relative_path)
        return self._disk.read_text(relative_path)

    def read_bytes(self, relative_path: str) -> bytes:
        self._broker.require(self._subject, "disk.read")
        self._require_path(relative_path)
        return self._disk.read_bytes(relative_path)

    def move(self, source: str, target: str) -> None:
        for permission in ("disk.read", "disk.write", "disk.delete"):
            self._broker.require(self._subject, permission)
        self._require_path(source)
        self._require_path(target)
        self._disk.move(source, target)

    def make_dir(self, relative_path: str) -> None:
        self._broker.require(self._subject, "disk.write")
        self._require_path(relative_path)
        self._disk.make_dir(relative_path)

    def write_text(self, relative_path: str, content: str, *, overwrite: bool = True) -> None:
        self._broker.require(self._subject, "disk.write")
        self._require_path(relative_path)
        self._disk.write_text(relative_path, content, overwrite=overwrite)

    def delete(self, relative_path: str) -> None:
        self._broker.require(self._subject, "disk.delete")
        self._require_path(relative_path)
        self._disk.delete(relative_path)

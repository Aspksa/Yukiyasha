"""Permission-checked access to Yukiyasha Disk for other modules."""

from yukiyasha.modules.disk.module import DiskModule
from yukiyasha.modules.permissions import PermissionBroker


class DiskAccess:
    """Expose only disk operations allowed by a module manifest."""

    def __init__(self, disk: DiskModule, broker: PermissionBroker, subject: str) -> None:
        self._disk = disk
        self._broker = broker
        self._subject = subject

    @property
    def state(self):
        return self._disk.state

    def list_entries(self, relative_path: str = "") -> list[dict[str, object]]:
        self._broker.require(self._subject, "disk.read")
        return self._disk.list_entries(relative_path)

    def read_text(self, relative_path: str) -> str:
        self._broker.require(self._subject, "disk.read")
        return self._disk.read_text(relative_path)

    def make_dir(self, relative_path: str) -> None:
        self._broker.require(self._subject, "disk.write")
        self._disk.make_dir(relative_path)

    def write_text(self, relative_path: str, content: str, *, overwrite: bool = True) -> None:
        self._broker.require(self._subject, "disk.write")
        self._disk.write_text(relative_path, content, overwrite=overwrite)

    def delete(self, relative_path: str) -> None:
        self._broker.require(self._subject, "disk.delete")
        self._disk.delete(relative_path)

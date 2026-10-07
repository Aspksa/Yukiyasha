"""Примавтодор: a work-project module (skeleton).

The module owns one folder on Yukiyasha Disk, ``projects/work/Примавтодор``, which shows up in
the "Рабочие" section of the UI. It only depends on the disk module, never on the web layer.
Domain features (documents, notes, search) are added on top of this skeleton later.
"""

from yukiyasha.modules.disk import DiskModule
from yukiyasha.modules.manifest import ModuleManifest
from yukiyasha.modules.registry import ModuleState
from yukiyasha.version import get_version

PRIMAVTODOR_DIR = "projects/work/Примавтодор"

PRIMAVTODOR_MANIFEST = ModuleManifest(
    module_id="primavtodor",
    name="Примавтодор",
    version=get_version(),
    description="Рабочий проект «Примавтодор»: папка и данные проекта на Диске Yukiyasha.",
    permissions=("disk.read", "disk.write"),
)


class PrimavtodorModule:
    manifest = PRIMAVTODOR_MANIFEST

    def __init__(self, disk: DiskModule) -> None:
        self._disk = disk
        self._state = ModuleState.REGISTERED
        self._last_error: str | None = None

    @property
    def state(self) -> ModuleState:
        return self._state

    @property
    def directory(self) -> str:
        """Project folder, relative to the disk root."""
        return PRIMAVTODOR_DIR

    def start(self) -> None:
        # Needs a READY disk (registered before this module); recreated if the user deleted it.
        self._disk.make_dir(PRIMAVTODOR_DIR)
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
            "directory": self.directory,
        }
        if self._last_error:
            health["error"] = self._last_error
        return {
            "manifest": self.manifest.to_dict(),
            "state": self.state.value,
            "health": health,
        }

"""Core Yukiyasha runtime."""

import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum

from yukiyasha.config import Settings
from yukiyasha.modules import ModuleRegistry
from yukiyasha.modules.ai import AiModule
from yukiyasha.modules.ai.tools import AiToolRegistry
from yukiyasha.modules.audit import AuditLog
from yukiyasha.modules.disk import DiskModule
from yukiyasha.modules.disk.access import DiskAccess
from yukiyasha.modules.permissions import PermissionBroker
from yukiyasha.modules.primavtodor import PrimavtodorModule
from yukiyasha.modules.primavtodor.access import PrimavtodorReadAccess

logger = logging.getLogger("yukiyasha.runtime")


class RuntimeState(StrEnum):
    STARTING = "starting"
    READY = "ready"
    DEGRADED = "degraded"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class RuntimeSnapshot:
    name: str
    version: str
    environment: str
    state: RuntimeState
    started_at: str | None

    def to_dict(self) -> dict[str, str | None]:
        payload = asdict(self)
        payload["state"] = self.state.value
        return payload


class YukiyashaRuntime:
    """Application kernel, module lifecycle and capability owner."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()
        self._started_at: datetime | None = None
        self._state = RuntimeState.STOPPED
        self.modules = ModuleRegistry()
        self.permissions = PermissionBroker()

        self.disk = DiskModule(self.settings.disk_dir)
        self.modules.register(self.disk)
        self.permissions.register(self.disk.manifest)

        primavtodor_disk = DiskAccess(
            self.disk,
            self.permissions,
            "primavtodor",
            roots=("projects/work/Примавтодор",),
        )
        self.primavtodor = PrimavtodorModule(primavtodor_disk)
        self.modules.register(self.primavtodor)
        self.permissions.register(self.primavtodor.manifest)

        self.audit = AuditLog(self.disk)
        ai_disk = DiskAccess(
            self.disk,
            self.permissions,
            "ai",
            roots=("ai",),
        )
        primavtodor_read = PrimavtodorReadAccess(
            self.primavtodor,
            self.permissions,
            "ai",
        )
        ai_tools = AiToolRegistry(primavtodor_read, self.audit)
        self.ai = AiModule(ai_disk, self.settings.ai, tools=ai_tools)
        self.modules.register(self.ai)
        self.permissions.register(self.ai.manifest)

    @property
    def state(self) -> RuntimeState:
        return self._state

    def start(self) -> None:
        self._state = RuntimeState.STARTING
        self._started_at = datetime.now(UTC)
        try:
            self.modules.start_all()
        except Exception:
            logger.exception("Module startup failed; runtime is degraded")
            self._state = RuntimeState.DEGRADED
            return
        self._state = RuntimeState.READY

    def stop(self) -> None:
        try:
            self.modules.stop_all()
        except Exception:
            logger.exception("Module shutdown failed")
            self._state = RuntimeState.DEGRADED
            raise
        self._state = RuntimeState.STOPPED

    def snapshot(self) -> RuntimeSnapshot:
        return RuntimeSnapshot(
            name=self.settings.app_name,
            version=self.settings.version,
            environment=self.settings.environment,
            state=self._state,
            started_at=self._started_at.isoformat() if self._started_at else None,
        )

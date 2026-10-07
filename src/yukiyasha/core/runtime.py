"""Core Yukiyasha runtime."""

import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum

from yukiyasha.config import Settings
from yukiyasha.modules import ModuleRegistry
from yukiyasha.modules.ai import AiModule
from yukiyasha.modules.disk import DiskModule
from yukiyasha.modules.primavtodor import PrimavtodorModule

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
    """Application kernel and module lifecycle owner."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()
        self._started_at: datetime | None = None
        self._state = RuntimeState.STOPPED
        self.modules = ModuleRegistry()
        self.disk = DiskModule(self.settings.disk_dir)
        self.modules.register(self.disk)
        # Registered after the disk it depends on: modules start in order, stop in reverse.
        self.primavtodor = PrimavtodorModule(self.disk)
        self.modules.register(self.primavtodor)
        self.ai = AiModule(self.disk, self.settings.ai)
        self.modules.register(self.ai)

    @property
    def state(self) -> RuntimeState:
        return self._state

    def start(self) -> None:
        self._state = RuntimeState.STARTING
        self._started_at = datetime.now(UTC)
        try:
            self.modules.start_all()
        except Exception:
            # Keep serving (health/modules report the failure) but never hide the cause.
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

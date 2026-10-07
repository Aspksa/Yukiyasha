"""Core Yukiyasha runtime."""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum

from yukiyasha.config import Settings
from yukiyasha.modules import ModuleRegistry
from yukiyasha.modules.disk import DiskModule


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
    started_at: str

    def to_dict(self) -> dict[str, str]:
        payload = asdict(self)
        payload["state"] = self.state.value
        return payload


class YukiyashaRuntime:
    """Application kernel and module lifecycle owner."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()
        self._started_at = datetime.now(UTC)
        self._state = RuntimeState.STARTING
        self.modules = ModuleRegistry()
        self.disk = DiskModule(self.settings.disk_dir)
        self.modules.register(self.disk)

    @property
    def state(self) -> RuntimeState:
        return self._state

    def start(self) -> None:
        try:
            self.modules.start_all()
        except Exception:
            self._state = RuntimeState.DEGRADED
            raise
        self._state = RuntimeState.READY

    def stop(self) -> None:
        self.modules.stop_all()
        self._state = RuntimeState.STOPPED

    def snapshot(self) -> RuntimeSnapshot:
        return RuntimeSnapshot(
            name=self.settings.app_name,
            version=self.settings.version,
            environment=self.settings.environment,
            state=self._state,
            started_at=self._started_at.isoformat(),
        )

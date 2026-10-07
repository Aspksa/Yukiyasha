"""Core Yukiyasha runtime."""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum

from yukiyasha.config import Settings


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
    """Small deterministic application kernel.

    The runtime owns process-level state. Future modules plug into this layer
    instead of coupling directly to the web interface.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()
        self._started_at = datetime.now(UTC)
        self._state = RuntimeState.STARTING

    @property
    def state(self) -> RuntimeState:
        return self._state

    def start(self) -> None:
        self._state = RuntimeState.READY

    def stop(self) -> None:
        self._state = RuntimeState.STOPPED

    def snapshot(self) -> RuntimeSnapshot:
        return RuntimeSnapshot(
            name=self.settings.app_name,
            version=self.settings.version,
            environment=self.settings.environment,
            state=self._state,
            started_at=self._started_at.isoformat(),
        )

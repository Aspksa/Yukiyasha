"""Permission-checked access to long-term assistant memory."""

from yukiyasha.modules.memory.module import MemoryModule
from yukiyasha.modules.permissions import PermissionBroker
from yukiyasha.modules.registry import ModuleState


class MemoryAccess:
    """Expose memory operations only when the caller has explicit capabilities."""

    def __init__(self, memory: MemoryModule, broker: PermissionBroker, subject: str) -> None:
        self._memory = memory
        self._broker = broker
        self._subject = subject

    def _ready(self) -> None:
        if self._memory.state is not ModuleState.READY:
            raise RuntimeError("Память не готова")

    def search(self, query: str, *, limit: int = 5) -> list[dict[str, object]]:
        self._broker.require(self._subject, "memory.read")
        self._ready()
        return self._memory.search(query, limit=limit)

    def remember(self, text: str) -> dict[str, object]:
        self._broker.require(self._subject, "memory.write")
        self._ready()
        return self._memory.remember(text)

    def forget(self, memory_id: str) -> None:
        self._broker.require(self._subject, "memory.delete")
        self._ready()
        self._memory.forget(memory_id)

    def forget_matching(self, query: str) -> str:
        self._broker.require(self._subject, "memory.delete")
        self._ready()
        return self._memory.forget_matching(query)

"""Read-only capability view of the Примавтодор module."""

from yukiyasha.modules.permissions import PermissionBroker
from yukiyasha.modules.primavtodor.module import PrimavtodorModule
from yukiyasha.modules.registry import ModuleState


class PrimavtodorReadAccess:
    """The only Примавтодор surface available to the assistant."""

    def __init__(
        self, module: PrimavtodorModule, broker: PermissionBroker, subject: str
    ) -> None:
        self._module = module
        self._broker = broker
        self._subject = subject

    def _check(self) -> None:
        self._broker.require(self._subject, "primavtodor.read")
        if self._module.state is not ModuleState.READY:
            raise RuntimeError("Примавтодор не готов")

    def list_records(self, kind: str) -> dict[str, object]:
        self._check()
        return self._module.data.list_records(kind)

    def get_record(self, kind: str, record_id: str) -> dict[str, object]:
        self._check()
        return self._module.data.get(kind, record_id)

    def timesheet(self, month: str) -> dict[str, object]:
        self._check()
        return self._module.timesheet.month_view(month)

    def settings(self) -> dict[str, object]:
        self._check()
        return self._module.settings.load()

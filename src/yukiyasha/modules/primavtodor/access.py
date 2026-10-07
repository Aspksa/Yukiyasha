"""Permission-checked capability views of the Примавтодор module."""

from yukiyasha.modules.permissions import PermissionBroker
from yukiyasha.modules.primavtodor.module import PrimavtodorModule
from yukiyasha.modules.registry import ModuleState


class _PrimavtodorAccess:
    def __init__(
        self, module: PrimavtodorModule, broker: PermissionBroker, subject: str
    ) -> None:
        self._module = module
        self._broker = broker
        self._subject = subject

    def _check(self, permission: str) -> None:
        self._broker.require(self._subject, permission)
        if self._module.state is not ModuleState.READY:
            raise RuntimeError("Примавтодор не готов")


class PrimavtodorReadAccess(_PrimavtodorAccess):
    """Read-only surface used by the assistant."""

    def list_records(self, kind: str) -> dict[str, object]:
        self._check("primavtodor.read")
        return self._module.data.list_records(kind)

    def get_record(self, kind: str, record_id: str) -> dict[str, object]:
        self._check("primavtodor.read")
        return self._module.data.get(kind, record_id)

    def timesheet(self, month: str) -> dict[str, object]:
        self._check("primavtodor.read")
        return self._module.timesheet.month_view(month)

    def settings(self) -> dict[str, object]:
        self._check("primavtodor.read")
        return self._module.settings.load()

    def list_documents(self, section_id: str, *, limit: int = 10) -> list[dict[str, object]]:
        self._check("primavtodor.read")
        return self._module.document_summaries(section_id, limit=limit)

    def read_document(self, section_id: str, name: str) -> dict[str, object]:
        self._check("primavtodor.read")
        return self._module.document_preview(section_id, name)


class PrimavtodorWriteAccess(_PrimavtodorAccess):
    """Mutation surface reserved for the proposal executor, never the AI module."""

    def validate(
        self,
        kind: str,
        payload: dict[str, object],
        *,
        record_id: str | None = None,
    ) -> dict[str, object]:
        self._check("primavtodor.write")
        return self._module.data.validate(kind, payload, record_id=record_id)

    def get_record(self, kind: str, record_id: str) -> dict[str, object]:
        self._check("primavtodor.read")
        return self._module.data.get(kind, record_id)

    def create(self, kind: str, payload: dict[str, object]) -> dict[str, object]:
        self._check("primavtodor.write")
        return self._module.data.create(kind, payload)

    def update(
        self, kind: str, record_id: str, payload: dict[str, object]
    ) -> dict[str, object]:
        self._check("primavtodor.write")
        return self._module.data.update(kind, record_id, payload)

    def delete(self, kind: str, record_id: str) -> None:
        self._check("primavtodor.delete")
        self._module.data.delete(kind, record_id)

"""Permission-checked AI access to proposal creation only."""

from yukiyasha.modules.permissions import PermissionBroker
from yukiyasha.modules.proposals.module import ProposalModule
from yukiyasha.modules.registry import ModuleState


class ProposalCreateAccess:
    """The assistant may draft proposals but can never apply or reject them."""

    def __init__(
        self, proposals: ProposalModule, broker: PermissionBroker, subject: str
    ) -> None:
        self._proposals = proposals
        self._broker = broker
        self._subject = subject

    def create(
        self,
        *,
        operation: str,
        kind: str,
        payload: dict[str, object] | None = None,
        record_id: str | None = None,
        reason: str = "",
    ) -> dict[str, object]:
        self._broker.require(self._subject, "proposal.create")
        if self._proposals.state is not ModuleState.READY:
            raise RuntimeError("Модуль предложений не готов")
        return self._proposals.create(
            operation=operation,
            kind=kind,
            payload=payload,
            record_id=record_id,
            reason=reason,
        )

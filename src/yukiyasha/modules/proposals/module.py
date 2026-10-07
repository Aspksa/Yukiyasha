"""Immutable-body proposal workflow for Примавтодор mutations."""

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime

from yukiyasha.modules.audit import AuditLog
from yukiyasha.modules.disk import DiskModule
from yukiyasha.modules.disk.access import DiskAccess
from yukiyasha.modules.manifest import ModuleManifest
from yukiyasha.modules.primavtodor.access import PrimavtodorWriteAccess
from yukiyasha.modules.primavtodor.errors import PrimavtodorError
from yukiyasha.modules.proposals.errors import (
    ProposalNotFoundError,
    ProposalStateError,
    ProposalValidationError,
)
from yukiyasha.modules.registry import ModuleState
from yukiyasha.version import get_version

PROPOSALS_DIR = "proposals/items"
PROPOSAL_ID_RE = re.compile(r"^prop-[0-9a-f]{12}$")
OPERATIONS = {"create", "update", "delete"}
KINDS = {"waybills", "fuel", "employees", "vehicles", "bookings"}

PROPOSALS_MANIFEST = ModuleManifest(
    module_id="proposals",
    name="Предложения",
    version=get_version(),
    description=(
        "Контур предложений изменений Примавтодора: тело предложения неизменно, "
        "применение возможно только после явного подтверждения человеком."
    ),
    permissions=(
        "disk.read",
        "disk.write",
        "primavtodor.read",
        "primavtodor.write",
        "primavtodor.delete",
    ),
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _fingerprint(record: dict[str, object]) -> str:
    stable = {
        "id": record.get("id"),
        "kind": record.get("kind"),
        "values": record.get("values"),
        "updated_at": record.get("updated_at"),
    }
    raw = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ProposalModule:
    manifest = PROPOSALS_MANIFEST

    def __init__(
        self,
        disk: DiskModule | DiskAccess,
        primavtodor: PrimavtodorWriteAccess,
        audit: AuditLog,
    ) -> None:
        self._disk = disk
        self._primavtodor = primavtodor
        self._audit = audit
        self._state = ModuleState.REGISTERED
        self._last_error: str | None = None

    @property
    def state(self) -> ModuleState:
        return self._state

    def start(self) -> None:
        self._disk.make_dir(PROPOSALS_DIR)
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
            "pending": (
                sum(1 for item in self.list_items() if item.get("status") == "pending")
                if self.state is ModuleState.READY
                else None
            ),
        }
        if self._last_error:
            health["error"] = self._last_error
        return {
            "manifest": self.manifest.to_dict(),
            "state": self.state.value,
            "health": health,
        }

    def _path(self, proposal_id: str) -> str:
        if not PROPOSAL_ID_RE.fullmatch(proposal_id):
            raise ProposalNotFoundError("Предложение не найдено")
        return f"{PROPOSALS_DIR}/{proposal_id}.json"

    def _load(self, proposal_id: str) -> dict[str, object]:
        try:
            payload = json.loads(self._disk.read_text(self._path(proposal_id)))
        except (FileNotFoundError, ValueError):
            raise ProposalNotFoundError("Предложение не найдено") from None
        if not isinstance(payload, dict) or payload.get("id") != proposal_id:
            raise ProposalNotFoundError("Предложение повреждено или не найдено")
        return payload

    def _save(self, proposal: dict[str, object]) -> None:
        self._disk.write_text(
            self._path(str(proposal["id"])),
            json.dumps(proposal, ensure_ascii=False, indent=2) + "\n",
            overwrite=True,
        )

    def list_items(self) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        for entry in self._disk.list_entries(PROPOSALS_DIR):
            name = str(entry["name"])
            if entry["type"] != "file" or not name.endswith(".json"):
                continue
            proposal_id = name.removesuffix(".json")
            if not PROPOSAL_ID_RE.fullmatch(proposal_id):
                continue
            try:
                items.append(self._load(proposal_id))
            except ProposalNotFoundError:
                continue
        items.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
        return items

    def get(self, proposal_id: str) -> dict[str, object]:
        return self._load(proposal_id)

    def create(
        self,
        *,
        operation: str,
        kind: str,
        payload: dict[str, object] | None = None,
        record_id: str | None = None,
        reason: str = "",
    ) -> dict[str, object]:
        if operation not in OPERATIONS:
            raise ProposalValidationError("Неизвестная операция")
        if kind not in KINDS:
            raise ProposalValidationError("Неизвестный тип записи")
        if operation == "create" and record_id:
            raise ProposalValidationError("Для создания record_id не указывается")
        if operation in {"update", "delete"} and not record_id:
            raise ProposalValidationError("Для изменения или удаления нужен record_id")

        body = dict(payload or {})
        base_fingerprint: str | None = None
        target_summary: dict[str, object] | None = None
        before: dict[str, object] | None = None

        if operation == "create":
            if not body:
                raise ProposalValidationError("Для создания нужны значения полей")
            normalized = self._primavtodor.validate(kind, body)
            body = normalized
        else:
            assert record_id is not None
            current = self._primavtodor.get_record(kind, record_id)
            base_fingerprint = _fingerprint(current)
            current_values = current.get("values")
            before = dict(current_values) if isinstance(current_values, dict) else {}
            target_summary = {
                "id": current.get("id"),
                "label": current.get("label"),
                "updated_at": current.get("updated_at"),
            }
            if operation == "update":
                if not body:
                    raise ProposalValidationError("Для изменения нужны значения полей")
                merged = {
                    **before,
                    **body,
                }
                body = self._primavtodor.validate(kind, merged, record_id=record_id)
            elif body:
                raise ProposalValidationError("Удаление не принимает значения полей")

        now = _now()
        proposal: dict[str, object] = {
            "id": f"prop-{uuid.uuid4().hex[:12]}",
            "status": "pending",
            "operation": operation,
            "kind": kind,
            "record_id": record_id,
            "payload": body,
            "before": before,
            "reason": " ".join(reason.split())[:500],
            "base_fingerprint": base_fingerprint,
            "target": target_summary,
            "created_at": now,
            "resolved_at": None,
            "result": None,
        }
        self._disk.write_text(
            self._path(str(proposal["id"])),
            json.dumps(proposal, ensure_ascii=False, indent=2) + "\n",
            overwrite=False,
        )
        self._audit.record(
            subject="ai",
            action="proposal.create",
            outcome="allowed",
            metadata={
                "proposal_id": proposal["id"],
                "operation": operation,
                "kind": kind,
                "record_id": record_id,
            },
        )
        return proposal

    def reject(self, proposal_id: str) -> dict[str, object]:
        proposal = self._load(proposal_id)
        self._require_pending(proposal)
        proposal["status"] = "rejected"
        proposal["resolved_at"] = _now()
        self._save(proposal)
        self._audit.record(
            subject="user",
            action="proposal.reject",
            outcome="allowed",
            metadata={"proposal_id": proposal_id},
        )
        return proposal

    def apply(self, proposal_id: str) -> dict[str, object]:
        proposal = self._load(proposal_id)
        self._require_pending(proposal)

        operation = str(proposal["operation"])
        kind = str(proposal["kind"])
        record_id = proposal.get("record_id")
        payload = proposal.get("payload")
        values = payload if isinstance(payload, dict) else {}

        if operation in {"update", "delete"}:
            assert isinstance(record_id, str)
            try:
                current = self._primavtodor.get_record(kind, record_id)
            except PrimavtodorError as exc:
                return self._mark_stale(proposal, type(exc).__name__)
            if _fingerprint(current) != proposal.get("base_fingerprint"):
                return self._mark_stale(proposal, "target_changed")

        try:
            if operation == "create":
                result = self._primavtodor.create(kind, values)
            elif operation == "update":
                assert isinstance(record_id, str)
                result = self._primavtodor.update(kind, record_id, values)
            else:
                assert isinstance(record_id, str)
                self._primavtodor.delete(kind, record_id)
                result = {"id": record_id, "deleted": True}
        except PrimavtodorError as exc:
            return self._mark_stale(proposal, type(exc).__name__)

        proposal["status"] = "applied"
        proposal["resolved_at"] = _now()
        proposal["result"] = {
            "id": result.get("id") if isinstance(result, dict) else record_id,
        }
        self._save(proposal)
        self._audit.record(
            subject="user",
            action="proposal.apply",
            outcome="allowed",
            metadata={
                "proposal_id": proposal_id,
                "operation": operation,
                "kind": kind,
                "record_id": record_id,
            },
        )
        return proposal

    def _mark_stale(
        self, proposal: dict[str, object], reason: str
    ) -> dict[str, object]:
        proposal["status"] = "stale"
        proposal["resolved_at"] = _now()
        proposal["result"] = {"reason": reason}
        self._save(proposal)
        self._audit.record(
            subject="user",
            action="proposal.apply",
            outcome="stale",
            metadata={
                "proposal_id": proposal["id"],
                "reason": reason,
            },
        )
        return proposal

    @staticmethod
    def _require_pending(proposal: dict[str, object]) -> None:
        if proposal.get("status") != "pending":
            raise ProposalStateError(
                f"Предложение уже завершено: {proposal.get('status')}"
            )

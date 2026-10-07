import json
from pathlib import Path

import pytest

from yukiyasha.modules.audit import AuditLog
from yukiyasha.modules.disk import DiskModule
from yukiyasha.modules.permissions import PermissionBroker, PermissionDeniedError
from yukiyasha.modules.primavtodor import PrimavtodorModule
from yukiyasha.modules.primavtodor.access import PrimavtodorWriteAccess
from yukiyasha.modules.proposals import (
    PROPOSALS_MANIFEST,
    ProposalCreateAccess,
    ProposalModule,
    ProposalStateError,
)


def started(tmp_path: Path) -> tuple[DiskModule, PrimavtodorModule, ProposalModule, PermissionBroker]:
    disk = DiskModule(tmp_path / "disk")
    disk.start()
    primavtodor = PrimavtodorModule(disk)
    primavtodor.start()

    broker = PermissionBroker()
    broker.register(PROPOSALS_MANIFEST)
    write = PrimavtodorWriteAccess(primavtodor, broker, "proposals")
    proposals = ProposalModule(disk, write, AuditLog(disk))
    proposals.start()
    return disk, primavtodor, proposals, broker


def vehicle_payload(plate: str = "А123АА25") -> dict[str, object]:
    return {
        "plate": plate,
        "model": "УАЗ Патриот",
        "fuel_type": "ДТ",
        "norm_summer": 14,
        "norm_winter": 16,
        "odometer_km": 1000,
        "active": True,
    }


def test_create_proposal_does_not_mutate_until_human_apply(tmp_path: Path) -> None:
    _, primavtodor, proposals, _ = started(tmp_path)

    proposal = proposals.create(
        operation="create",
        kind="vehicles",
        payload=vehicle_payload(),
        reason="Добавить новую машину",
    )

    assert proposal["status"] == "pending"
    assert primavtodor.data.list_records("vehicles")["records"] == []

    applied = proposals.apply(str(proposal["id"]))
    records = primavtodor.data.list_records("vehicles")["records"]

    assert applied["status"] == "applied"
    assert len(records) == 1
    assert records[0]["values"]["plate"] == "А123АА25"
    assert applied["result"]["id"] == records[0]["id"]

    with pytest.raises(ProposalStateError):
        proposals.apply(str(proposal["id"]))


def test_partial_update_proposal_is_normalized_and_becomes_stale_after_change(
    tmp_path: Path,
) -> None:
    _, primavtodor, proposals, _ = started(tmp_path)
    vehicle = primavtodor.data.create("vehicles", vehicle_payload())

    proposal = proposals.create(
        operation="update",
        kind="vehicles",
        record_id=str(vehicle["id"]),
        payload={"model": "УАЗ Патриот обновлённый"},
        reason="Исправить модель",
    )

    assert proposal["payload"]["plate"] == "А123АА25"
    assert proposal["payload"]["model"] == "УАЗ Патриот обновлённый"

    primavtodor.data.update(
        "vehicles",
        str(vehicle["id"]),
        {**vehicle["values"], "odometer_km": 1200},
    )
    stale = proposals.apply(str(proposal["id"]))

    assert stale["status"] == "stale"
    current = primavtodor.data.get("vehicles", str(vehicle["id"]))
    assert current["values"]["model"] == "УАЗ Патриот"
    assert current["values"]["odometer_km"] == 1200


def test_delete_proposal_reject_is_final_and_preserves_record(tmp_path: Path) -> None:
    _, primavtodor, proposals, _ = started(tmp_path)
    vehicle = primavtodor.data.create("vehicles", vehicle_payload())

    proposal = proposals.create(
        operation="delete",
        kind="vehicles",
        record_id=str(vehicle["id"]),
        reason="Машина выбыла",
    )
    rejected = proposals.reject(str(proposal["id"]))

    assert rejected["status"] == "rejected"
    assert primavtodor.data.get("vehicles", str(vehicle["id"]))["id"] == vehicle["id"]
    with pytest.raises(ProposalStateError):
        proposals.apply(str(proposal["id"]))


def test_ai_proposal_access_has_create_only_and_is_default_deny(tmp_path: Path) -> None:
    _, _, proposals, broker = started(tmp_path)

    denied = ProposalCreateAccess(proposals, broker, "ai")
    with pytest.raises(PermissionDeniedError):
        denied.create(
            operation="create",
            kind="vehicles",
            payload=vehicle_payload(),
        )

    # The facade intentionally exposes no apply/reject methods.
    assert not hasattr(denied, "apply")
    assert not hasattr(denied, "reject")


def test_proposal_audit_omits_payload(tmp_path: Path) -> None:
    disk, _, proposals, _ = started(tmp_path)

    proposal = proposals.create(
        operation="create",
        kind="vehicles",
        payload=vehicle_payload("SECRET-PLATE"),
        reason="Техническая проверка",
    )
    proposals.apply(str(proposal["id"]))

    audit_files = list((tmp_path / "disk" / "system" / "audit").rglob("*.json"))
    assert len(audit_files) == 2
    text = "\n".join(path.read_text(encoding="utf-8") for path in audit_files)

    assert "SECRET-PLATE" not in text
    assert str(proposal["id"]) in text
    assert '"proposal.create"' in text
    assert '"proposal.apply"' in text

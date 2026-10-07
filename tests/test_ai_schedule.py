"""The assistant reads the schedule and the summary, and books only through a proposal."""

import json
from datetime import date
from pathlib import Path

import pytest

from tests.test_primavtodor_records import make_vehicle
from yukiyasha.modules.ai.tools import AiToolRegistry
from yukiyasha.modules.audit import AuditLog
from yukiyasha.modules.disk import DiskModule
from yukiyasha.modules.manifest import ModuleManifest
from yukiyasha.modules.permissions import PermissionBroker
from yukiyasha.modules.primavtodor import PrimavtodorModule, PrimavtodorReadAccess
from yukiyasha.modules.primavtodor.access import PrimavtodorWriteAccess
from yukiyasha.modules.proposals import PROPOSALS_MANIFEST, ProposalCreateAccess, ProposalModule


@pytest.fixture
def setup(tmp_path: Path):
    disk = DiskModule(tmp_path / "disk")
    disk.start()
    module = PrimavtodorModule(disk)
    module.start()
    broker = PermissionBroker()
    broker.register(PROPOSALS_MANIFEST)
    broker.register(
        ModuleManifest(
            module_id="ai",
            name="ai",
            version="test",
            description="test",
            permissions=("primavtodor.read", "proposal.create"),
        )
    )
    proposals = ProposalModule(
        disk, PrimavtodorWriteAccess(module, broker, "proposals"), AuditLog(disk)
    )
    proposals.start()
    tools = AiToolRegistry(
        PrimavtodorReadAccess(module, broker, "ai"),
        AuditLog(disk),
        proposals=ProposalCreateAccess(proposals, broker, "ai"),
    )
    car = make_vehicle(module, plate="С 303 СС", model="HINO 500")
    driver = module.data.create(
        "employees",
        {"full_name": "Веровский Игорь Павлович", "is_driver": True, "vehicle_id": car["id"]},
    )
    return module, proposals, tools, car, driver


def call(tools: AiToolRegistry, name: str, arguments: dict, message: str) -> dict:
    return json.loads(tools.execute(name, arguments, message))


def test_schedule_questions_offer_the_read_tools(setup) -> None:
    _, _, tools, _, _ = setup
    names = {d["function"]["name"] for d in tools.definitions("Кто сейчас в командировке?")}
    assert {"primavtodor_schedule", "primavtodor_briefing", "primavtodor_parse_booking"} <= names
    assert "primavtodor_propose_change" not in names  # no intent to change anything


def test_the_assistant_reads_the_schedule_and_the_summary(setup) -> None:
    module, _, tools, car, driver = setup
    module.bookings.create(
        {"vehicle_id": car["id"], "driver_id": driver["id"], "date_from": "2026-10-07",
         "date_to": "2026-10-09", "kind": "trip", "note": "Находка"}
    )  # fmt: skip

    schedule = call(tools, "primavtodor_schedule", {"day": "2026-10-08", "days": 7}, "график")

    assert schedule["bookings"][0]["driver"] == "Веровский Игорь Павлович"
    assert schedule["free_vehicles"] == [] and schedule["free_drivers"] == []
    assert "error" not in call(tools, "primavtodor_briefing", {}, "сводка")
    bad = call(tools, "primavtodor_schedule", {"day": "не дата"}, "график")
    assert "error" in bad


def test_a_booking_is_only_a_proposal_until_the_user_approves(setup) -> None:
    module, proposals, tools, car, driver = setup
    message = "Запиши Веровского в командировку с 7 по 9"
    text = "Веровский 7-9 командировка"
    guess = call(tools, "primavtodor_parse_booking", {"text": text}, message)
    assert guess["values"]["vehicle_id"] == car["id"]

    proposal = call(
        tools,
        "primavtodor_propose_change",
        {"operation": "create", "kind": "bookings", "payload": guess["values"],
         "reason": "Просили по телефону"},
        message,
    )  # fmt: skip

    assert proposal["status"] == "pending" and proposal["kind"] == "bookings"
    assert "Веровский И." in proposal["reason"] and "С303СС" in proposal["reason"].replace(" ", "")
    assert module.bookings.overview(date(2026, 10, 1), 31, date(2026, 10, 1))["bookings"] == []

    proposals.apply(str(proposal["id"]))
    view = module.bookings.overview(date(2026, 10, 1), 31, date(2026, 10, 1))
    assert len(view["bookings"]) == 1 and view["bookings"][0]["driver_id"] == driver["id"]


def test_a_booking_can_be_changed_and_removed_by_proposal(setup) -> None:
    module, proposals, tools, car, driver = setup
    created = module.bookings.create(
        {"vehicle_id": car["id"], "driver_id": driver["id"], "date_from": "2026-10-07",
         "date_to": "2026-10-09", "kind": "trip"}
    )  # fmt: skip

    change = proposals.create(
        operation="update", kind="bookings", record_id=created["id"],
        payload={"date_to": "2026-10-10"}, reason="Продлили",
    )  # fmt: skip
    assert change["before"]["date_to"] == "2026-10-09"
    proposals.apply(str(change["id"]))
    assert module.bookings.record(created["id"])["values"]["date_to"] == "2026-10-10"

    gone = proposals.create(operation="delete", kind="bookings", record_id=created["id"])
    proposals.apply(str(gone["id"]))
    with pytest.raises(Exception):  # noqa: B017 - RecordNotFoundError
        module.bookings.record(created["id"])

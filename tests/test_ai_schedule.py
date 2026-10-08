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


def test_natural_booking_verbs_open_the_proposal_tool(setup) -> None:
    _, _, tools, _, _ = setup
    for message in (
        "Забронируй машину на среду",
        "Перенеси поездку Веровского на пятницу",
        "Отмени командировку",
        "Продли выезд на день",
    ):
        names = {d["function"]["name"] for d in tools.definitions(message)}
        assert "primavtodor_propose_change" in names, message


def test_a_long_schedule_says_it_was_cut(setup) -> None:
    module, _, tools, car, driver = setup
    for day in range(1, 29):  # 28 days x 2 trips: more than the tool returns
        for _ in range(2):
            module.bookings.create(
                {"vehicle_id": car["id"], "driver_id": driver["id"],
                 "date_from": f"2026-11-{day:02d}", "date_to": f"2026-11-{day:02d}", "kind": "trip"}
            )  # fmt: skip

    result = call(tools, "primavtodor_schedule", {"day": "2026-11-01", "days": 31}, "график")

    assert result["bookings_total"] == 56 and result["bookings_truncated"] is True
    assert len(result["bookings"]) == 40


def test_parse_then_propose_in_one_turn(setup, tmp_path: Path) -> None:
    """«Запиши Веровского 7-9»: the proposal needs the answer of the parser first."""
    from tests.fake_provider import FakeProvider
    from yukiyasha.config import AiSettings
    from yukiyasha.modules.ai import AiModule

    module, proposals, tools, car, driver = setup
    values = {
        "vehicle_id": car["id"], "driver_id": driver["id"], "date_from": "2026-10-07",
        "date_to": "2026-10-09", "kind": "trip", "note": "",
    }  # fmt: skip
    parse = {"id": "c1", "type": "function", "function": {
        "name": "primavtodor_parse_booking", "arguments": json.dumps({"text": "Веровский 7-9"})}}
    propose = {"id": "c2", "type": "function", "function": {
        "name": "primavtodor_propose_change", "arguments": json.dumps(
            {"operation": "create", "kind": "bookings", "payload": values})}}  # fmt: skip

    with FakeProvider(chunks=["Предложила."], tool_rounds=[[parse], [propose]]) as provider:
        disk = DiskModule(tmp_path / "ai-disk")
        disk.start()
        assistant = AiModule(
            disk,
            AiSettings(base_url=provider.base_url, model="m", api_key="k"),
            tools=tools,
        )
        assistant.start()
        turn = assistant.begin_chat(None, "Запиши Веровского в командировку 7-9")
        events = list(turn.events())
        turn.release()

    assert events[-1]["type"] == "done"
    pending = [p for p in proposals.list_items() if p["status"] == "pending"]
    assert len(pending) == 1 and pending[0]["kind"] == "bookings"
    assert pending[0]["payload"]["date_to"] == "2026-10-09"


def test_the_summary_is_built_from_the_normalized_booking(setup) -> None:
    _, _, tools, car, driver = setup
    payload = {"vehicle_id": car["id"], "driver_id": driver["id"], "date_from": "2026-10-07"}
    proposal = call(
        tools,
        "primavtodor_propose_change",
        {"operation": "create", "kind": "bookings", "payload": payload},
        "Запиши выезд",
    )

    assert "None" not in proposal["reason"]
    assert "07.10.2026" in proposal["reason"] and "Командировка" in proposal["reason"]
    assert proposal["payload"]["date_to"] == "2026-10-07"


def test_terse_booking_orders_reach_the_tools_and_chatter_does_not(setup) -> None:
    _, _, tools, _, _ = setup
    orders = ("Запиши Веровского 7-9", "Забронируй на среду", "Отмени бронь", "Продли Игоря до 12")
    for message in orders:
        assert tools.might_need_tools(message), message
        names = {d["function"]["name"] for d in tools.definitions(message)}
        assert "primavtodor_propose_change" in names, message
    for message in ("Запиши мой номер телефона", "Привет, как дела?", "Расскажи анекдот"):
        assert not tools.might_need_tools(message), message


def test_every_cancel_and_move_verb_reaches_the_tools(setup) -> None:
    _, _, tools, _, _ = setup
    for message in (
        "Отмени Веровского 9",
        "Сократи Веровского до 9",
        "Убери Веровского 9",
        "Сдвинь Веровского на 10",
    ):
        names = {d["function"]["name"] for d in tools.definitions(message)}
        assert "primavtodor_propose_change" in names, message


def test_an_update_proposal_describes_the_booking_after_the_change(setup) -> None:
    module, _, tools, car, driver = setup
    other = make_vehicle(module, plate="Л 777 ЛЛ", model="Lexus")
    created = module.bookings.create(
        {"vehicle_id": car["id"], "driver_id": driver["id"], "date_from": "2026-10-07",
         "date_to": "2026-10-09", "kind": "trip"}
    )  # fmt: skip

    proposal = call(
        tools,
        "primavtodor_propose_change",
        {"operation": "update", "kind": "bookings", "record_id": created["id"],
         "payload": {"vehicle_id": other["id"], "date_to": "2026-10-10"}},
        "Перенеси Веровского на Лексус до 10",
    )  # fmt: skip

    assert "error" not in proposal, proposal
    assert "Л777ЛЛ" in proposal["reason"].replace(" ", "")  # the new car, not the old one
    assert "10.2026" in proposal["reason"] and "10.10.2026" in proposal["reason"]


def test_a_repeated_proposal_call_is_executed_once(setup, tmp_path: Path) -> None:
    from tests.fake_provider import FakeProvider
    from yukiyasha.config import AiSettings
    from yukiyasha.modules.ai import AiModule

    module, proposals, tools, car, driver = setup
    values = {"vehicle_id": car["id"], "driver_id": driver["id"], "date_from": "2026-10-07"}
    propose = {"id": "c1", "type": "function", "function": {
        "name": "primavtodor_propose_change", "arguments": json.dumps(
            {"operation": "create", "kind": "bookings", "payload": values})}}  # fmt: skip
    again = {**propose, "id": "c2"}  # the model repeats it after seeing the result

    with FakeProvider(chunks=["Готово."], tool_rounds=[[propose], [again]]) as provider:
        disk = DiskModule(tmp_path / "ai-disk")
        disk.start()
        assistant = AiModule(
            disk, AiSettings(base_url=provider.base_url, model="m", api_key="k"), tools=tools
        )
        assistant.start()
        turn = assistant.begin_chat(None, "Запиши Веровского 7")
        list(turn.events())
        turn.release()

    assert len([p for p in proposals.list_items() if p["status"] == "pending"]) == 1


def test_a_null_days_argument_means_the_default_window(setup) -> None:
    _, _, tools, _, _ = setup
    result = call(tools, "primavtodor_schedule", {"days": None, "day": None}, "график")
    assert "error" not in result and result["bookings_total"] == 0
    listing = call(tools, "primavtodor_list_records", {"kind": "vehicles", "limit": None}, "машины")
    assert "error" not in listing


def test_the_verb_set_is_defined_once_and_matches_both_gates() -> None:
    import re

    from yukiyasha.modules.ai import tools as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert len(re.findall(r"^BOOKING_VERBS = ", source, re.MULTILINE)) == 1
    for message in ("Перенесём Веровского на 10", "Перенеси Веровского на 10"):
        assert module.BUSINESS_TRIGGER.search(message), message
        assert module.MUTATION_TRIGGER.search(message), message


def test_tool_answers_never_overflow_the_context_across_rounds(setup, tmp_path: Path) -> None:
    from tests.fake_provider import FakeProvider
    from yukiyasha.config import AiSettings
    from yukiyasha.modules.ai import AiModule

    module, _, tools, car, driver = setup
    for day in range(1, 29):  # a long schedule: the answer is several thousand characters
        module.bookings.create(
            {"vehicle_id": car["id"], "driver_id": driver["id"], "kind": "trip",
             "date_from": f"2026-11-{day:02d}", "date_to": f"2026-11-{day:02d}"}
        )  # fmt: skip

    def read(call_id: str, days: int) -> dict:
        arguments = json.dumps({"day": "2026-11-01", "days": days})
        return {"id": call_id, "type": "function",
                "function": {"name": "primavtodor_schedule", "arguments": arguments}}  # fmt: skip

    rounds = [[read("a", 31)], [read("b", 30)], [read("c", 29)]]
    with FakeProvider(chunks=["ok"], tool_rounds=rounds) as provider:
        disk = DiskModule(tmp_path / "ai-disk")
        disk.start()
        settings = AiSettings(
            base_url=provider.base_url, model="m", api_key="k", max_context_chars=9000
        )
        assistant = AiModule(disk, settings, tools=tools)
        assistant.start()
        turn = assistant.begin_chat(None, "Покажи график машин")
        list(turn.events())
        turn.release()

    final = provider.requests[-1]["body"]["messages"]
    assert sum(len(str(m.get("content") or "")) for m in final) <= 9000


def test_a_question_about_a_booking_cannot_create_a_proposal(setup) -> None:
    _, _, tools, _, _ = setup
    for message in ("Какая бронь на завтра?", "Покажи брони на неделю"):
        assert tools.might_need_tools(message)  # the schedule can be read
        names = {d["function"]["name"] for d in tools.definitions(message)}
        assert "primavtodor_propose_change" not in names, message
        attempt = {"operation": "create", "kind": "bookings", "payload": {}}
        denied = call(tools, "primavtodor_propose_change", attempt, message)
        assert denied == {"error": "Доступ к действию запрещён"}


def test_calls_that_cannot_report_back_are_not_executed(setup, tmp_path: Path) -> None:
    from tests.fake_provider import FakeProvider
    from yukiyasha.config import AiSettings
    from yukiyasha.modules.ai import AiModule

    module, proposals, tools, car, driver = setup
    for day in range(1, 29):
        module.bookings.create(
            {"vehicle_id": car["id"], "driver_id": driver["id"], "kind": "trip",
             "date_from": f"2026-11-{day:02d}", "date_to": f"2026-11-{day:02d}"}
        )  # fmt: skip
    values = {"vehicle_id": car["id"], "driver_id": driver["id"], "date_from": "2026-12-01"}
    schedule = {"id": "a", "type": "function", "function": {
        "name": "primavtodor_schedule", "arguments": json.dumps({"day": "2026-11-01", "days": 31})}}
    propose = {"id": "b", "type": "function", "function": {
        "name": "primavtodor_propose_change", "arguments": json.dumps(
            {"operation": "create", "kind": "bookings", "payload": values})}}  # fmt: skip

    with FakeProvider(chunks=["ok"], tool_rounds=[[schedule, propose]]) as provider:
        disk = DiskModule(tmp_path / "ai-disk")
        disk.start()
        settings = AiSettings(base_url=provider.base_url, model="m", api_key="k",
                              max_context_chars=6000)  # the schedule alone fills it
        assistant = AiModule(disk, settings, tools=tools)
        assistant.start()
        turn = assistant.begin_chat(None, "Покажи график машин и запиши Веровского на 1 декабря")
        list(turn.events())
        turn.release()

    assert [p for p in proposals.list_items() if p["status"] == "pending"] == []
    answers = [m for m in provider.requests[-1]["body"]["messages"] if m["role"] == "tool"]
    assert len(answers) == 2 and "Не выполнено" in answers[1]["content"]

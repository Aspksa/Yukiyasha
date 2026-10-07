from pathlib import Path

from tests.fake_provider import FakeProvider
from yukiyasha.config import AiSettings
from yukiyasha.modules.ai import AiModule
from yukiyasha.modules.disk import DiskModule


class StubTools:
    names = ("primavtodor_list_records",)

    def might_need_tools(self, message: str) -> bool:
        return "путев" in message.lower()

    def definitions(self, message: str = "") -> list[dict[str, object]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "primavtodor_list_records",
                    "description": "read",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

    def execute(
        self,
        name: str,
        arguments: dict[str, object],
        user_message: str = "",
    ) -> str:
        assert name == "primavtodor_list_records"
        assert arguments == {"kind": "waybills"}
        assert "путев" in user_message.lower()
        return '{"kind":"waybills","records":[{"id":"wb-1"}]}'


def test_ai_executes_provider_tool_plan_before_streaming_final_answer(tmp_path: Path) -> None:
    calls = [
        {
            "id": "call-1",
            "type": "function",
            "function": {
                "name": "primavtodor_list_records",
                "arguments": '{"kind":"waybills"}',
            },
        }
    ]
    with FakeProvider(chunks=["Нашла один путевой лист."], tool_calls=calls) as provider:
        settings = AiSettings(
            base_url=provider.base_url,
            model="test-model",
            api_key="secret",
        )
        disk = DiskModule(tmp_path / "disk")
        disk.start()
        module = AiModule(disk, settings, tools=StubTools())  # type: ignore[arg-type]
        module.start()

        events = list(module.begin_chat(None, "Покажи путевые листы").events())

    assert events[-1]["type"] == "done"
    assert len(provider.requests) == 2
    assert provider.requests[0]["body"]["tools"][0]["function"]["name"] == (
        "primavtodor_list_records"
    )
    final_messages = provider.requests[1]["body"]["messages"]
    assert any(message["role"] == "tool" for message in final_messages)
    tool_message = next(message for message in final_messages if message["role"] == "tool")
    assert "wb-1" in tool_message["content"]


def test_ai_does_not_send_tools_for_unrelated_chat(tmp_path: Path) -> None:
    with FakeProvider(chunks=["Привет"]) as provider:
        settings = AiSettings(base_url=provider.base_url, model="test-model", api_key="secret")
        disk = DiskModule(tmp_path / "disk")
        disk.start()
        module = AiModule(disk, settings, tools=StubTools())  # type: ignore[arg-type]
        module.start()

        list(module.begin_chat(None, "Привет").events())

    assert len(provider.requests) == 1
    assert "tools" not in provider.requests[0]["body"]



class DocumentStubTools:
    names = ("primavtodor_list_documents",)

    def might_need_tools(self, message: str) -> bool:
        return "документ" in message.lower()

    def definitions(self, message: str = "") -> list[dict[str, object]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "primavtodor_list_documents",
                    "description": "documents",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

    def execute(
        self,
        name: str,
        arguments: dict[str, object],
        user_message: str = "",
    ) -> str:
        assert name == "primavtodor_list_documents"
        return (
            '{"section_id":"memos","documents":[{'
            '"section_id":"memos","section_title":"Служебные записки",'
            '"name":"записка-12.md",'
            '"path":"projects/work/Примавтодор/Служебные записки/записка-12.md",'
            '"size":321,"extension":"md","preview":"Прошу выделить автомобиль."'
            '}]}'
        )


def test_ai_persists_document_refs_and_emits_document_event(tmp_path: Path) -> None:
    calls = [
        {
            "id": "doc-call",
            "type": "function",
            "function": {
                "name": "primavtodor_list_documents",
                "arguments": '{"section_id":"memos"}',
            },
        }
    ]
    with FakeProvider(chunks=["Нашла служебную записку."], tool_calls=calls) as provider:
        settings = AiSettings(base_url=provider.base_url, model="test-model", api_key="secret")
        disk = DiskModule(tmp_path / "disk")
        disk.start()
        module = AiModule(disk, settings, tools=DocumentStubTools())  # type: ignore[arg-type]
        module.start()

        events = list(module.begin_chat(None, "Покажи документы").events())

    document_event = next(event for event in events if event["type"] == "documents")
    document = document_event["documents"][0]
    assert document["name"] == "записка-12.md"
    assert document["section_title"] == "Служебные записки"

    conversation_id = str(events[0]["conversation_id"])
    chat = module.get_chat(conversation_id)
    reply = chat["messages"][-1]
    assert reply["role"] == "assistant"
    assert reply["documents"][0]["path"].endswith("/записка-12.md")

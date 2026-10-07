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

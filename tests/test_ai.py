import json
from pathlib import Path

import pytest

from tests.fake_provider import FakeProvider
from yukiyasha.config import AiSettings
from yukiyasha.modules.ai import (
    AiBusyError,
    AiModule,
    AiNotConfiguredError,
    ConversationNotFoundError,
    MessageRejectedError,
    ProviderError,
)
from yukiyasha.modules.ai.persona_pack import persona_text
from yukiyasha.modules.disk import DiskModule

SECRET = "sk-test-SECRET-123"


def settings_for(provider: FakeProvider, **overrides) -> AiSettings:
    values = {"base_url": provider.base_url, "model": "test-model", "api_key": SECRET}
    return AiSettings(**{**values, **overrides})


def make_module(tmp_path: Path, settings: AiSettings) -> AiModule:
    disk = DiskModule(tmp_path / "disk")
    disk.start()
    module = AiModule(disk, settings)
    module.start()
    return module


def ask(module: AiModule, message: str, chat_id: str | None = None) -> list[dict]:
    turn = module.begin_chat(chat_id, message)
    try:
        return list(turn.events())
    finally:
        turn.release()


# ----- settings -----

def test_settings_never_show_the_key() -> None:
    settings = AiSettings(base_url="https://api.example.com/v1", model="m", api_key=SECRET)

    assert SECRET not in repr(settings)
    assert SECRET not in str(settings)
    assert settings.configured and settings.provider_host == "api.example.com"


@pytest.mark.parametrize(
    ("kwargs", "fragment"),
    [
        ({}, "не настроен"),
        ({"base_url": "https://x", "model": "m"}, "YUKIYASHA_AI_API_KEY"),
        ({"base_url": "https://x", "api_key": "k"}, "YUKIYASHA_AI_MODEL"),
        ({"base_url": "http://api.example.com", "model": "m", "api_key": "k"}, "https://"),
        ({"base_url": "ftp://x", "model": "m", "api_key": "k"}, "https://"),
    ],
)
def test_incomplete_or_unsafe_settings_explain_the_problem(kwargs: dict, fragment: str) -> None:
    settings = AiSettings(**kwargs)

    assert not settings.configured
    assert fragment in settings.problem


def test_plain_http_is_fine_for_a_local_model() -> None:
    assert AiSettings(base_url="http://localhost:11434/v1", model="m", api_key="k").configured
    assert AiSettings(base_url="http://127.0.0.1:8080/v1", model="m", api_key="k").configured


def test_settings_come_from_the_environment_and_an_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / "ai.env"
    env_file.write_text(
        "# comment\nYUKIYASHA_AI_BASE_URL=https://file.example/v1\n"
        'YUKIYASHA_AI_MODEL="file-model"\nYUKIYASHA_AI_API_KEY=file-key\n',
        encoding="utf-8",
    )

    from_file = AiSettings.from_env({"YUKIYASHA_AI_ENV_FILE": str(env_file)})
    mixed = AiSettings.from_env(
        {"YUKIYASHA_AI_ENV_FILE": str(env_file), "YUKIYASHA_AI_MODEL": "env-model",
         "YUKIYASHA_AI_MAX_TOKENS": "512", "YUKIYASHA_AI_TIMEOUT": "oops"}
    )

    assert from_file.model == "file-model" and from_file.api_key == "file-key"
    assert mixed.model == "env-model" and mixed.base_url == "https://file.example/v1"  # env wins
    assert mixed.max_tokens == 512 and mixed.timeout == 120.0  # bad number -> default


# ----- chatting -----

def test_streams_the_answer_and_saves_the_conversation(tmp_path: Path) -> None:
    with FakeProvider() as provider:
        module = make_module(tmp_path, settings_for(provider))

        events = ask(module, "  Привет  ")

        request = provider.requests[0]
    assert request["path"] == "/v1/chat/completions"
    assert request["auth"] == f"Bearer {SECRET}"
    assert request["body"]["model"] == "test-model" and request["body"]["stream"] is True
    assert request["body"]["max_tokens"] == 2048
    assert request["body"]["messages"][0]["role"] == "system"
    assert request["body"]["messages"][-1] == {"role": "user", "content": "Привет"}

    assert [e["type"] for e in events] == ["meta", "delta", "delta", "delta", "done"]
    assert "".join(e["text"] for e in events if e["type"] == "delta") == "Привет, мир"
    chat = module.get_chat(events[0]["conversation_id"])
    assert [m["role"] for m in chat["messages"]] == ["user", "assistant"]
    assert chat["messages"][1]["content"] == "Привет, мир"
    assert chat["title"] == "Привет"


def test_a_conversation_continues_with_its_history(tmp_path: Path) -> None:
    with FakeProvider(chunks=["ответ"]) as provider:
        module = make_module(tmp_path, settings_for(provider))
        chat_id = ask(module, "первый вопрос")[0]["conversation_id"]

        ask(module, "второй вопрос", chat_id)

        sent = provider.requests[1]["body"]["messages"]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "user"]
    assert sent[1]["content"] == "первый вопрос" and sent[3]["content"] == "второй вопрос"
    assert len(module.get_chat(chat_id)["messages"]) == 4
    assert [c["id"] for c in module.list_chats()] == [chat_id]


def test_old_history_is_trimmed_to_the_context_budget(tmp_path: Path) -> None:
    with FakeProvider(chunks=["ok"]) as provider:
        budget = len(persona_text(AiSettings().assistant_name)) + 700
        module = make_module(tmp_path, settings_for(provider, max_context_chars=budget))
        chat_id = ask(module, "a" * 300)[0]["conversation_id"]
        for letter in "bcd":
            ask(module, letter * 300, chat_id)

        ask(module, "последний", chat_id)

        sent = provider.requests[-1]["body"]["messages"]
    texts = [m["content"] for m in sent]
    assert "a" * 300 not in texts  # the oldest turn no longer fits
    assert texts[-1] == "последний" and sent[0]["role"] == "system"
    assert sum(len(t) for t in texts) <= budget + len(texts[-1])


def test_persona_is_created_once_and_sent_as_the_system_prompt(tmp_path: Path) -> None:
    with FakeProvider(chunks=["ok"]) as provider:
        module = make_module(tmp_path, settings_for(provider, assistant_name="Саюри"))
        assert "Саюри" in module.persona()

        module.set_persona("Ты — строгий бухгалтер.")
        module.stop()
        module.start()  # a restart must not overwrite the edited persona
        ask(module, "Вопрос")

        assert module.persona().strip() == "Ты — строгий бухгалтер."
        assert provider.requests[0]["body"]["messages"][0]["content"].strip() == (
            "Ты — строгий бухгалтер."
        )
    with pytest.raises(MessageRejectedError):
        module.set_persona("   ")


def test_a_plain_json_answer_works_too(tmp_path: Path) -> None:
    with FakeProvider(chunks=["целый ответ"], plain_json=True) as provider:
        module = make_module(tmp_path, settings_for(provider))

        events = ask(module, "вопрос")

    assert "".join(e["text"] for e in events if e["type"] == "delta") == "целый ответ"


# ----- errors never leak the key and never leave a half-written chat -----

@pytest.mark.parametrize(
    ("status", "fragment"),
    [(401, "отклонил ключ"), (403, "отклонил ключ"), (404, "не нашёл адрес"),
     (429, "ограничил"), (500, "недоступен"), (400, "отклонил запрос")],
)
def test_provider_errors_are_explained_and_save_nothing(
    tmp_path: Path, status: int, fragment: str
) -> None:
    with FakeProvider(status=status) as provider:
        module = make_module(tmp_path, settings_for(provider))

        with pytest.raises(ProviderError) as exc:
            module.begin_chat(None, "вопрос")

    assert fragment in exc.value.message and exc.value.status == status
    assert module.list_chats() == []  # a failed request leaves no conversation behind


def test_a_key_echoed_by_the_provider_is_scrubbed(tmp_path: Path) -> None:
    body = {"error": {"message": f"Incorrect API key provided: {SECRET}"}}
    with FakeProvider(status=400, error_body=body) as provider:
        module = make_module(tmp_path, settings_for(provider))

        with pytest.raises(ProviderError) as exc:
            module.begin_chat(None, "вопрос")

    assert SECRET not in exc.value.message and "***" in exc.value.message


def test_an_unreachable_provider_is_reported_without_the_key(tmp_path: Path) -> None:
    settings = AiSettings(base_url="http://127.0.0.1:9/v1", model="m", api_key=SECRET, timeout=2)
    module = make_module(tmp_path, settings)

    with pytest.raises(ProviderError) as exc:
        module.begin_chat(None, "вопрос")

    assert "Нет связи" in exc.value.message and SECRET not in exc.value.message


def test_an_empty_answer_is_an_error_and_is_not_saved(tmp_path: Path) -> None:
    with FakeProvider(chunks=[]) as provider:
        module = make_module(tmp_path, settings_for(provider))

        with pytest.raises(MessageRejectedError):
            ask(module, "вопрос")

    assert module.list_chats() == []


def test_message_validation_and_missing_settings(tmp_path: Path) -> None:
    with FakeProvider() as provider:
        module = make_module(tmp_path, settings_for(provider))
        for bad in ("", "   ", "x" * 8001):
            with pytest.raises(MessageRejectedError):
                module.begin_chat(None, bad)
        assert not provider.requests
    unconfigured = make_module(tmp_path / "other", AiSettings())
    with pytest.raises(AiNotConfiguredError):
        unconfigured.begin_chat(None, "привет")


def test_unknown_conversation_ids_are_rejected(tmp_path: Path) -> None:
    with FakeProvider() as provider:
        module = make_module(tmp_path, settings_for(provider))
        for bad in ("chat-00000000", "../../etc/passwd", "chat-xyz", ""):
            with pytest.raises(ConversationNotFoundError):
                module.get_chat(bad)
        with pytest.raises(ConversationNotFoundError):
            module.begin_chat("chat-00000000", "привет")


def test_concurrent_requests_are_limited(tmp_path: Path) -> None:
    with FakeProvider() as provider:
        module = make_module(tmp_path, settings_for(provider))
        first = module.begin_chat(None, "один")
        second = module.begin_chat(None, "два")

        with pytest.raises(AiBusyError):
            module.begin_chat(None, "три")

        first.release()
        third = module.begin_chat(None, "три")  # a slot is free again
        second.release()
        third.release()
        first.release()  # releasing twice is harmless
        assert module._slots.acquire(blocking=False)


def test_delete_chat_and_snapshot_hide_the_key(tmp_path: Path) -> None:
    with FakeProvider() as provider:
        module = make_module(tmp_path, settings_for(provider))
        chat_id = ask(module, "привет")[0]["conversation_id"]

        module.delete_chat(chat_id)

        assert module.list_chats() == []
        assert SECRET not in json.dumps(module.snapshot()) + json.dumps(module.status())
        assert module.snapshot()["health"]["configured"] is True


def test_the_key_is_never_written_to_the_disk(tmp_path: Path) -> None:
    with FakeProvider(chunks=[f"echo {SECRET}"]) as provider:  # even if the model repeated it
        module = make_module(tmp_path, settings_for(provider))
        ask(module, "привет")
        module.set_persona("Ты — помощник.")

    # Only the provider's *answer* may contain what the provider chose to say; the module itself
    # must not add the key anywhere: check everything except the stored answer text.
    for path in (tmp_path / "disk").rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            if path.suffix == ".json":
                data = json.loads(text)
                for message in data.get("messages", []):
                    message.pop("content", None) if message["role"] == "assistant" else None
                text = json.dumps(data, ensure_ascii=False)
            assert SECRET not in text, f"key found in {path}"


# ----- character pack -----

def test_default_persona_is_the_character_and_an_old_default_is_upgraded(tmp_path: Path) -> None:
    from yukiyasha.modules.ai.module import OLD_DEFAULT_PERSONA
    from yukiyasha.modules.ai.persona_pack import (
        V04_PROGRAM_RULES,
        V05_PROGRAM_RULES,
        V06_PROGRAM_RULES,
        persona_text,
    )

    with FakeProvider(chunks=["ok"]) as provider:
        settings = settings_for(provider, assistant_name="Юкияша")
        module = make_module(tmp_path, settings)
        persona = module.persona()
        assert "Господин" in persona and "read-only инструменты Примавтодора" in persona

        module.set_persona(OLD_DEFAULT_PERSONA.format(name="Юкияша"))
        module.stop()
        module.start()  # the untouched v0.3.0 default becomes the current character
        assert module.persona() == persona

        module.set_persona(
            persona_text("Юкияша", program_rules=V04_PROGRAM_RULES)
        )
        module.stop()
        module.start()  # an untouched v0.4.0 persona gets the current rules too
        assert module.persona() == persona

        module.set_persona(
            persona_text("Юкияша", program_rules=V05_PROGRAM_RULES)
        )
        module.stop()
        module.start()  # an untouched v0.5.0 persona gets proposal rules too
        assert module.persona() == persona

        module.set_persona(
            persona_text("Юкияша", program_rules=V06_PROGRAM_RULES)
        )
        module.stop()
        module.start()  # untouched v0.6/v0.7 persona gets document-card rules
        assert module.persona() == persona


def test_tone_examples_fit_the_message_and_do_not_repeat(tmp_path: Path) -> None:
    with FakeProvider(chunks=["ok"]) as provider:
        module = make_module(tmp_path, settings_for(provider))
        chat_id = ask(module, "Привет!")[0]["conversation_id"]
        ask(module, "Привет ещё раз", chat_id)

        first, second = (r["body"]["messages"][0]["content"] for r in provider.requests)
    assert "Примеры твоего тона" in first and "Примеры твоего тона" in second

    def lines(text: str) -> set[str]:
        return set(text.split("Примеры твоего тона")[1].splitlines()[1:])

    assert lines(first).isdisjoint(lines(second))
    saved = module.get_chat(chat_id)["messages"]
    ids = [m.get("examples") for m in saved if m["role"] == "assistant"]
    assert len(ids[0]) == 3 and set(ids[0]).isdisjoint(ids[1])


def test_no_examples_without_a_match_or_in_a_crisis(tmp_path: Path) -> None:
    with FakeProvider(chunks=["ok"]) as provider:
        module = make_module(tmp_path, settings_for(provider))
        ask(module, "Сколько будет 2+2?")
        ask(module, "Привет, мне так плохо, не хочу жить")

        for request in provider.requests:
            assert "Примеры твоего тона" not in request["body"]["messages"][0]["content"]
    assert all("examples" not in m for chat in module.list_chats()
               for m in module.get_chat(chat["id"])["messages"])

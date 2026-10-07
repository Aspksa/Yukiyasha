"""AI assistant module: persona, conversations on the disk and a pluggable chat provider.

Everything the assistant remembers lives as plain files on Yukiyasha Disk, so it can be read,
edited and backed up with ordinary tools:

    ai/persona.md            who the assistant is and how it answers (edit it any time)
    ai/chats/chat-*.json     one file per conversation

The module depends only on the disk module. It sends the persona and the conversation to the
provider and nothing else: it has no access to the Примавтодор data (that comes later, read-only).
"""

import json
import re
import threading
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

from yukiyasha.config import AiSettings
from yukiyasha.modules.ai.errors import (
    AiBusyError,
    AiNotConfiguredError,
    ConversationNotFoundError,
    MessageRejectedError,
)
from yukiyasha.modules.ai.persona_pack import (
    RECENT_WINDOW,
    format_examples,
    persona_text,
    pick_examples,
)
from yukiyasha.modules.ai.provider import ChatProvider, Message, OpenAICompatibleProvider
from yukiyasha.modules.disk import DiskConflictError, DiskModule
from yukiyasha.modules.manifest import ModuleManifest
from yukiyasha.modules.registry import ModuleState
from yukiyasha.version import get_version

PERSONA_PATH = "ai/persona.md"
CHATS_DIR = "ai/chats"
CHAT_ID_RE = re.compile(r"^chat-[0-9a-f]{8}$")
MAX_MESSAGE_CHARS = 8_000
MAX_PERSONA_CHARS = 8_000
MAX_CONCURRENT = 2
TITLE_CHARS = 60

AI_MANIFEST = ModuleManifest(
    module_id="ai",
    name="Помощник",
    version=get_version(),
    description=(
        "Личный ИИ-помощник: личность и диалоги хранятся на Диске, ответы даёт выбранная "
        "модель по вашему ключу."
    ),
    permissions=("disk.read", "disk.write", "ai.provider"),
)

# The persona written by v0.3.0; a file that still equals it is upgraded to the character pack.
OLD_DEFAULT_PERSONA = """Ты — {name}, личный помощник пользователя в программе Yukiyasha.

Правила:
- Отвечай по-русски, коротко и по делу.
- Если не уверен — так и скажи. Не выдумывай факты, цифры, даты и номера документов.
- Сейчас ты НЕ видишь данные программы (путевые листы, сотрудников, ГСМ, табель, документы).
  Не делай вид, что видишь их: если спрашивают о таких данных, объясни, что доступа пока нет.
- Ничего не удаляешь и не меняешь сам: только предлагаешь, решение за пользователем.
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class ChatTurn:
    """One question being answered. Iterate :meth:`events`; always call :meth:`release` after."""

    def __init__(
        self,
        module: "AiModule",
        chat: dict[str, object],
        user_text: str,
        stream: Iterator[str],
        slot: threading.BoundedSemaphore,
        example_ids: list[str] | None = None,
    ) -> None:
        self.conversation_id = str(chat["id"])
        self._module = module
        self._chat = chat
        self._user_text = user_text
        self._stream = stream
        self._slot = slot
        self._example_ids = example_ids or []
        self._released = False

    def events(self) -> Iterator[dict[str, object]]:
        """Yield ``meta``, then ``delta`` events and finally ``done`` (after the chat is saved)."""
        yield {"type": "meta", "conversation_id": self.conversation_id}
        parts: list[str] = []
        try:
            for chunk in self._stream:
                parts.append(chunk)
                yield {"type": "delta", "text": chunk}
            answer = "".join(parts).strip()
            if not answer:
                raise MessageRejectedError("Провайдер вернул пустой ответ")
            self._module._save_turn(self._chat, self._user_text, answer, self._example_ids)
            yield {"type": "done", "conversation_id": self.conversation_id}
        finally:
            self.release()

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        close = getattr(self._stream, "close", None)
        if close is not None:
            close()
        self._slot.release()


class AiModule:
    manifest = AI_MANIFEST

    def __init__(
        self,
        disk: DiskModule,
        settings: AiSettings | None = None,
        provider: ChatProvider | None = None,
    ) -> None:
        self._disk = disk
        self.settings = settings or AiSettings()
        self._provider = provider
        self._slots = threading.BoundedSemaphore(MAX_CONCURRENT)
        self._state = ModuleState.REGISTERED
        self._last_error: str | None = None

    @property
    def state(self) -> ModuleState:
        return self._state

    # ----- lifecycle -----

    def start(self) -> None:
        self._disk.make_dir(CHATS_DIR)
        default = persona_text(self.settings.assistant_name)
        try:  # keep a persona the user already edited
            self._disk.write_text(PERSONA_PATH, default, overwrite=False)
        except DiskConflictError:
            old = OLD_DEFAULT_PERSONA.format(name=self.settings.assistant_name)
            if self._disk.read_text(PERSONA_PATH) == old:
                self._disk.write_text(PERSONA_PATH, default, overwrite=True)
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
            "configured": self.settings.configured,
            "provider": self.settings.provider_host,
            "model": self.settings.model or None,
        }
        if self._last_error:
            health["error"] = self._last_error
        return {"manifest": self.manifest.to_dict(), "state": self.state.value, "health": health}

    # ----- status & persona -----

    def status(self) -> dict[str, object]:
        """Safe to show: never contains the key."""
        settings = self.settings
        return {
            "configured": settings.configured,
            "problem": settings.problem,
            "provider": settings.provider_host,
            "model": settings.model or None,
            "assistant_name": settings.assistant_name,
            "persona_path": PERSONA_PATH,
            "limits": {
                "max_message_chars": MAX_MESSAGE_CHARS,
                "max_tokens": settings.max_tokens,
                "max_context_chars": settings.max_context_chars,
            },
        }

    def persona(self) -> str:
        return self._disk.read_text(PERSONA_PATH)

    def set_persona(self, text: str) -> None:
        text = text.strip()
        if not text:
            raise MessageRejectedError("Описание личности не может быть пустым")
        if len(text) > MAX_PERSONA_CHARS:
            raise MessageRejectedError(f"Слишком длинно: не больше {MAX_PERSONA_CHARS} символов")
        self._disk.write_text(PERSONA_PATH, text + "\n", overwrite=True)

    # ----- conversations -----

    def _chat_path(self, chat_id: str) -> str:
        if not CHAT_ID_RE.match(chat_id):
            raise ConversationNotFoundError("Диалог не найден")
        return f"{CHATS_DIR}/{chat_id}.json"

    def get_chat(self, chat_id: str) -> dict[str, object]:
        try:
            data = json.loads(self._disk.read_text(self._chat_path(chat_id)))
        except (FileNotFoundError, ValueError):
            raise ConversationNotFoundError("Диалог не найден") from None
        if not isinstance(data, dict) or data.get("id") != chat_id:
            raise ConversationNotFoundError("Диалог не найден")
        return data

    def list_chats(self) -> list[dict[str, object]]:
        chats: list[dict[str, object]] = []
        for entry in self._disk.list_entries(CHATS_DIR):
            name = str(entry["name"])
            chat_id = name.removesuffix(".json")
            is_chat = entry["type"] == "file" and name.endswith(".json")
            if not (is_chat and CHAT_ID_RE.match(chat_id)):
                continue
            try:
                chat = self.get_chat(chat_id)
            except ConversationNotFoundError:
                continue
            messages = chat.get("messages")
            chats.append(
                {
                    "id": chat_id,
                    "title": chat.get("title") or "Без названия",
                    "updated_at": chat.get("updated_at"),
                    "messages": len(messages) if isinstance(messages, list) else 0,
                }
            )
        chats.sort(key=lambda item: str(item["updated_at"] or ""), reverse=True)
        return chats

    def delete_chat(self, chat_id: str) -> None:
        self.get_chat(chat_id)
        self._disk.delete(self._chat_path(chat_id))

    def _save_turn(
        self, chat: dict[str, object], user_text: str, answer: str, example_ids: list[str]
    ) -> None:
        now = _now()
        messages = chat.setdefault("messages", [])
        assert isinstance(messages, list)
        messages.append({"role": "user", "content": user_text, "at": now})
        reply: dict[str, object] = {"role": "assistant", "content": answer, "at": now}
        if example_ids:
            reply["examples"] = example_ids
        messages.append(reply)
        if not chat.get("title"):
            chat["title"] = " ".join(user_text.split())[:TITLE_CHARS]
        chat["updated_at"] = now
        text = json.dumps(chat, ensure_ascii=False, indent=2) + "\n"
        self._disk.write_text(self._chat_path(str(chat["id"])), text, overwrite=True)

    # ----- chatting -----

    def _context(
        self, persona: str, history: list[object], user_text: str
    ) -> tuple[list[Message], list[str]]:
        """System prompt + as much recent history as fits the budget + the new message.

        Also returns the ids of the tone examples added to the system prompt.
        """
        recent = [
            str(i)
            for item in history[-RECENT_WINDOW:]
            if isinstance(item, dict) and isinstance(item.get("examples"), list)
            for i in item["examples"]
        ]
        examples = pick_examples(user_text, recent)
        persona += format_examples(examples)
        budget = self.settings.max_context_chars - len(persona) - len(user_text)
        kept: list[Message] = []
        used = 0
        for item in reversed(history):
            if not isinstance(item, dict) or item.get("role") not in {"user", "assistant"}:
                continue
            content = str(item.get("content", ""))
            if used + len(content) > budget:
                break
            kept.append({"role": str(item["role"]), "content": content})
            used += len(content)
        kept.reverse()
        system: Message = {"role": "system", "content": persona}
        messages: list[Message] = [system, *kept, {"role": "user", "content": user_text}]
        return messages, [str(e["id"]) for e in examples]

    def begin_chat(self, chat_id: str | None, message: str) -> ChatTurn:
        """Validate, connect to the provider and return the turn to stream.

        Nothing is written to the disk until the whole answer has arrived, so a failed request
        leaves no half-finished conversation behind.
        """
        text = message.strip()
        if not text:
            raise MessageRejectedError("Введите сообщение")
        if len(text) > MAX_MESSAGE_CHARS:
            raise MessageRejectedError(f"Сообщение длиннее {MAX_MESSAGE_CHARS} символов")
        if not self.settings.configured:
            raise AiNotConfiguredError(self.settings.problem or "ИИ не настроен")
        if self._state is not ModuleState.READY:
            raise AiNotConfiguredError("Модуль помощника не запущен")

        if chat_id:
            chat = self.get_chat(chat_id)
        else:
            chat = {"id": f"chat-{uuid.uuid4().hex[:8]}", "title": "", "created_at": _now(),
                    "messages": []}

        if not self._slots.acquire(blocking=False):
            raise AiBusyError("Помощник уже обрабатывает запросы — подождите немного")
        try:
            history = chat.get("messages")
            context, example_ids = self._context(
                self.persona(), history if isinstance(history, list) else [], text
            )
            provider = self._provider or OpenAICompatibleProvider(self.settings)
            stream = provider.open(context)
        except BaseException:
            self._slots.release()
            raise
        return ChatTurn(self, chat, text, stream, self._slots, example_ids)

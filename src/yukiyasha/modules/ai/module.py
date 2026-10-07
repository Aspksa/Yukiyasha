"""AI assistant module with local persona, chats and read-only business tools."""

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
    LEGACY_PROGRAM_RULES,
    RECENT_WINDOW,
    V04_PROGRAM_RULES,
    V05_PROGRAM_RULES,
    V06_PROGRAM_RULES,
    format_examples,
    persona_text,
    pick_examples,
)
from yukiyasha.modules.ai.provider import ChatProvider, Message, OpenAICompatibleProvider
from yukiyasha.modules.ai.tools import AiToolRegistry
from yukiyasha.modules.disk import DiskConflictError, DiskModule
from yukiyasha.modules.disk.access import DiskAccess
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
        "модель по вашему ключу; данные Примавтодора доступны на чтение, а изменения — "
        "только как предложения с отдельным подтверждением человеком."
    ),
    permissions=(
        "disk.read",
        "disk.write",
        "disk.delete",
        "ai.provider",
        "primavtodor.read",
        "memory.read",
        "memory.write",
        "memory.delete",
        "proposal.create",
    ),
)

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


def _document_refs(tool_name: str, content: str) -> list[dict[str, object]]:
    if tool_name != "primavtodor_list_documents":
        return []
    try:
        payload = json.loads(content)
    except ValueError:
        return []
    raw_items = payload.get("documents", []) if isinstance(payload, dict) else []
    if not isinstance(raw_items, list):
        return []
    refs: list[dict[str, object]] = []
    for item in raw_items[:10]:
        if not isinstance(item, dict) or not item.get("path") or not item.get("name"):
            continue
        refs.append(
            {
                key: item[key]
                for key in (
                    "section_id",
                    "section_title",
                    "name",
                    "path",
                    "size",
                    "extension",
                    "preview",
                    "truncated",
                )
                if key in item
            }
        )
    return refs


class ChatTurn:
    """One question being answered. Iterate :meth:`events`; always release afterwards."""

    def __init__(
        self,
        module: "AiModule",
        chat: dict[str, object],
        user_text: str,
        stream: Iterator[str],
        slot: threading.BoundedSemaphore,
        example_ids: list[str] | None = None,
        documents: list[dict[str, object]] | None = None,
    ) -> None:
        self.conversation_id = str(chat["id"])
        self._module = module
        self._chat = chat
        self._user_text = user_text
        self._stream = stream
        self._slot = slot
        self._example_ids = example_ids or []
        self._documents = documents or []
        self._released = False

    def events(self) -> Iterator[dict[str, object]]:
        yield {"type": "meta", "conversation_id": self.conversation_id}
        parts: list[str] = []
        try:
            for chunk in self._stream:
                parts.append(chunk)
                yield {"type": "delta", "text": chunk}
            answer = "".join(parts).strip()
            if not answer:
                raise MessageRejectedError("Провайдер вернул пустой ответ")
            self._module._save_turn(
                self._chat,
                self._user_text,
                answer,
                self._example_ids,
                self._documents,
            )
            if self._documents:
                yield {"type": "documents", "documents": self._documents}
            yield {"type": "done", "conversation_id": self.conversation_id}
        finally:
            self.release()

    def __del__(self) -> None:
        # A response dropped before the stream started never reaches the generator's ``finally``.
        try:
            self.release()
        except Exception:  # noqa: BLE001 - never raise from a finaliser
            pass

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
        disk: DiskModule | DiskAccess,
        settings: AiSettings | None = None,
        provider: ChatProvider | None = None,
        tools: AiToolRegistry | None = None,
    ) -> None:
        self._disk = disk
        self.settings = settings or AiSettings()
        self._provider = provider
        self._tools = tools
        self._slots = threading.BoundedSemaphore(MAX_CONCURRENT)
        self._save_lock = threading.Lock()
        self._state = ModuleState.REGISTERED
        self._last_error: str | None = None

    @property
    def state(self) -> ModuleState:
        return self._state

    def start(self) -> None:
        self._disk.make_dir(CHATS_DIR)
        default = persona_text(self.settings.assistant_name)
        try:
            self._disk.write_text(PERSONA_PATH, default, overwrite=False)
        except DiskConflictError:
            current = self._disk.read_text(PERSONA_PATH)
            old_plain = OLD_DEFAULT_PERSONA.format(name=self.settings.assistant_name)
            old_character = persona_text(
                self.settings.assistant_name,
                program_rules=LEGACY_PROGRAM_RULES,
            )
            v04_character = persona_text(
                self.settings.assistant_name,
                program_rules=V04_PROGRAM_RULES,
            )
            v05_character = persona_text(
                self.settings.assistant_name,
                program_rules=V05_PROGRAM_RULES,
            )
            v06_character = persona_text(
                self.settings.assistant_name,
                program_rules=V06_PROGRAM_RULES,
            )
            if current in {
                old_plain,
                old_character,
                v04_character,
                v05_character,
                v06_character,
            }:
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
            "tools": list(self._tools.names) if self._tools else [],
        }
        if self._last_error:
            health["error"] = self._last_error
        return {"manifest": self.manifest.to_dict(), "state": self.state.value, "health": health}

    def status(self) -> dict[str, object]:
        settings = self.settings
        return {
            "configured": settings.configured,
            "problem": settings.problem,
            "provider": settings.provider_host,
            "model": settings.model or None,
            "assistant_name": settings.assistant_name,
            "persona_path": PERSONA_PATH,
            "tools": list(self._tools.names) if self._tools else [],
            "tool_access": "guarded" if self._tools else "none",
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
        self,
        chat: dict[str, object],
        user_text: str,
        answer: str,
        example_ids: list[str],
        documents: list[dict[str, object]] | None = None,
    ) -> None:
        with self._save_lock:
            self._append_turn(chat, user_text, answer, example_ids, documents)

    def _append_turn(
        self,
        chat: dict[str, object],
        user_text: str,
        answer: str,
        example_ids: list[str],
        documents: list[dict[str, object]] | None,
    ) -> None:
        try:  # another turn may have saved to this conversation while this one was streaming
            chat = self.get_chat(str(chat["id"]))
        except ConversationNotFoundError:
            pass
        now = _now()
        messages = chat.setdefault("messages", [])
        assert isinstance(messages, list)
        messages.append({"role": "user", "content": user_text, "at": now})
        reply: dict[str, object] = {"role": "assistant", "content": answer, "at": now}
        if example_ids:
            reply["examples"] = example_ids
        if documents:
            reply["documents"] = documents
        messages.append(reply)
        if not chat.get("title"):
            chat["title"] = " ".join(user_text.split())[:TITLE_CHARS]
        chat["updated_at"] = now
        text = json.dumps(chat, ensure_ascii=False, indent=2) + "\n"
        self._disk.write_text(self._chat_path(str(chat["id"])), text, overwrite=True)

    def _context(
        self, persona: str, history: list[object], user_text: str
    ) -> tuple[list[Message], list[str]]:
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

    def _add_tool_results(
        self, provider: ChatProvider, context: list[Message], user_text: str
    ) -> tuple[list[Message], list[dict[str, object]]]:
        if not self._tools or not self._tools.might_need_tools(user_text):
            return context, []
        planner = getattr(provider, "plan_tools", None)
        if not callable(planner):
            return context, []
        plan = planner(context, self._tools.definitions(user_text))
        if plan is None:
            return context, []
        enriched = [*context, plan.message]
        documents: list[dict[str, object]] = []
        seen_paths: set[str] = set()
        for call in plan.calls:
            content = self._tools.execute(
                call.name,
                call.arguments,
                user_text,
            )
            enriched.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "name": call.name,
                    "content": content,
                }
            )
            for document in _document_refs(call.name, content):
                path = str(document.get("path", ""))
                if path and path not in seen_paths:
                    seen_paths.add(path)
                    documents.append(document)
        return enriched, documents

    def begin_chat(self, chat_id: str | None, message: str) -> ChatTurn:
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
            chat = {
                "id": f"chat-{uuid.uuid4().hex[:8]}",
                "title": "",
                "created_at": _now(),
                "messages": [],
            }

        if not self._slots.acquire(blocking=False):
            raise AiBusyError("Помощник уже обрабатывает запросы — подождите немного")
        try:
            history = chat.get("messages")
            context, example_ids = self._context(
                self.persona(), history if isinstance(history, list) else [], text
            )
            provider = self._provider or OpenAICompatibleProvider(self.settings)
            context, documents = self._add_tool_results(provider, context, text)
            stream = provider.open(context)
        except BaseException:
            self._slots.release()
            raise
        return ChatTurn(
            self,
            chat,
            text,
            stream,
            self._slots,
            example_ids,
            documents,
        )

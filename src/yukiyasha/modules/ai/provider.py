"""Client for OpenAI-compatible chat APIs with optional read-only tool planning."""

import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

from yukiyasha.config import AiSettings
from yukiyasha.modules.ai.errors import ProviderError

Message = dict[str, object]
MAX_ERROR_TEXT = 300
MAX_TOOL_CALLS = 4


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, object]


@dataclass(frozen=True, slots=True)
class ToolPlan:
    message: Message
    calls: tuple[ToolCall, ...]


class ChatProvider(Protocol):
    def open(self, messages: list[Message]) -> Iterator[str]:
        """Connect and return streamed text chunks."""
        ...


class OpenAICompatibleProvider:
    def __init__(self, settings: AiSettings) -> None:
        self._settings = settings

    def _scrub(self, text: str) -> str:
        key = self._settings.api_key
        cleaned = text.replace(key, "***") if key else text
        return cleaned.strip()[:MAX_ERROR_TEXT]

    def _http_error(self, exc: urllib.error.HTTPError) -> ProviderError:
        status = exc.code
        detail = ""
        try:
            payload = json.loads(exc.read().decode("utf-8", "replace"))
            error = payload.get("error") if isinstance(payload, dict) else None
            detail = str(error.get("message") if isinstance(error, dict) else error or "")
        except (ValueError, OSError, AttributeError):
            pass
        detail = self._scrub(detail)
        if status in (401, 403):
            message = "Провайдер отклонил ключ (проверьте YUKIYASHA_AI_API_KEY)"
        elif status == 404:
            message = "Провайдер не нашёл адрес или модель (проверьте BASE_URL и MODEL)"
        elif status == 429:
            message = "Провайдер ограничил число запросов или закончился лимит; повторите позже"
        elif status in (400, 422):
            message = f"Провайдер отклонил запрос: {detail or status}"
        elif status >= 500:
            message = f"Сервис провайдера недоступен (код {status}); повторите позже"
        else:
            message = (
                f"Провайдер ответил ошибкой {status}: {detail}"
                if detail
                else f"Провайдер ответил ошибкой {status}"
            )
        return ProviderError(message, status)

    def _request(self, payload: dict[str, object], accept: str) -> object:
        settings = self._settings
        request = urllib.request.Request(
            f"{settings.base_url.rstrip('/')}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": accept,
                "Authorization": f"Bearer {settings.api_key}",
            },
        )
        try:
            return urllib.request.urlopen(request, timeout=settings.timeout)  # noqa: S310
        except urllib.error.HTTPError as exc:
            raise self._http_error(exc) from None
        except TimeoutError:
            raise ProviderError("Провайдер не ответил вовремя") from None
        except (urllib.error.URLError, OSError):
            raise ProviderError(
                f"Нет связи с провайдером ({settings.provider_host or 'адрес не задан'})"
            ) from None

    def plan_tools(
        self, messages: list[Message], tools: list[dict[str, object]]
    ) -> ToolPlan | None:
        """Ask for standard OpenAI tool calls before the final streamed answer.

        Providers that reject the standard tools fields with 400/422 are treated as
        tool-incompatible and the assistant falls back to ordinary chat.
        """
        payload: dict[str, object] = {
            "model": self._settings.model,
            "messages": messages,
            "stream": False,
            "max_tokens": min(self._settings.max_tokens, 512),
            "tools": tools,
            "tool_choice": "auto",
        }
        try:
            response = self._request(payload, "application/json")
        except ProviderError as exc:
            if exc.status in {400, 422}:
                return None
            raise

        with response:  # type: ignore[attr-defined]
            try:
                data = json.loads(
                    response.read().decode("utf-8", "replace")  # type: ignore[attr-defined]
                )
                message = data["choices"][0]["message"]
                raw_calls = message.get("tool_calls")
            except (ValueError, KeyError, IndexError, TypeError, AttributeError):
                raise ProviderError(
                    "Провайдер вернул план инструментов в неожиданном формате"
                ) from None

        if not isinstance(raw_calls, list) or not raw_calls:
            return None

        calls: list[ToolCall] = []
        for item in raw_calls[:MAX_TOOL_CALLS]:
            try:
                function = item["function"]
                name = str(function["name"])
                raw_arguments = function.get("arguments") or "{}"
                arguments = (
                    json.loads(raw_arguments)
                    if isinstance(raw_arguments, str)
                    else raw_arguments
                )
                if not isinstance(arguments, dict):
                    raise TypeError
                call_id = str(item["id"])
            except (KeyError, TypeError, ValueError, AttributeError):
                raise ProviderError("Провайдер вернул некорректный вызов инструмента") from None
            calls.append(ToolCall(call_id, name, arguments))

        assistant_message: Message = {
            "role": "assistant",
            "content": message.get("content"),
            "tool_calls": raw_calls[:MAX_TOOL_CALLS],
        }
        return ToolPlan(assistant_message, tuple(calls))

    def open(self, messages: list[Message]) -> Iterator[str]:
        response = self._request(
            {
                "model": self._settings.model,
                "messages": messages,
                "stream": True,
                "max_tokens": self._settings.max_tokens,
            },
            "text/event-stream",
        )
        return self._read(response)

    def _read(self, response: object) -> Iterator[str]:
        """Yield the text of a streamed (SSE) or, as a fallback, a plain JSON answer."""
        with response:  # type: ignore[attr-defined]
            content_type = response.headers.get_content_type()  # type: ignore[attr-defined]
            if content_type == "application/json":
                try:
                    data = json.loads(
                        response.read().decode("utf-8", "replace")  # type: ignore[attr-defined]
                    )
                    text = data["choices"][0]["message"]["content"]
                except (ValueError, KeyError, IndexError, TypeError):
                    raise ProviderError("Провайдер вернул ответ в неожиданном формате") from None
                if text:
                    yield str(text)
                return

            try:
                for raw in response:  # type: ignore[attr-defined]
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data_text = line[5:].strip()
                    if data_text == "[DONE]":
                        return
                    try:
                        delta = json.loads(data_text)["choices"][0].get("delta", {})
                    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
                        continue
                    text = delta.get("content") if isinstance(delta, dict) else None
                    if text:
                        yield str(text)
            except (TimeoutError, OSError):
                raise ProviderError("Связь с провайдером оборвалась") from None

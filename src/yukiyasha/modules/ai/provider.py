"""Client for OpenAI-compatible chat APIs (OpenAI, DeepSeek, Cloud.ru, Ollama, vLLM, ...).

Only the standard library is used, so there is no extra dependency. The API key is sent in the
``Authorization`` header and is scrubbed from every error text before it can reach a user or a log.
"""

import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import Protocol

from yukiyasha.config import AiSettings
from yukiyasha.modules.ai.errors import ProviderError

Message = dict[str, str]
MAX_ERROR_TEXT = 300


class ChatProvider(Protocol):
    def open(self, messages: list[Message]) -> Iterator[str]:
        """Connect (raising ProviderError at once on failure) and return the text chunks."""
        ...


class OpenAICompatibleProvider:
    def __init__(self, settings: AiSettings) -> None:
        self._settings = settings

    # ----- helpers -----

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
            message = f"Провайдер ответил ошибкой {status}: {detail}" if detail else (
                f"Провайдер ответил ошибкой {status}"
            )
        return ProviderError(message, status)

    # ----- public -----

    def open(self, messages: list[Message]) -> Iterator[str]:
        settings = self._settings
        url = f"{settings.base_url.rstrip('/')}/chat/completions"
        body = json.dumps(
            {
                "model": settings.model,
                "messages": messages,
                "stream": True,
                "max_tokens": settings.max_tokens,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "Authorization": f"Bearer {settings.api_key}",
            },
        )
        try:
            response = urllib.request.urlopen(request, timeout=settings.timeout)  # noqa: S310
        except urllib.error.HTTPError as exc:
            raise self._http_error(exc) from None
        except TimeoutError:
            raise ProviderError("Провайдер не ответил вовремя") from None
        except (urllib.error.URLError, OSError):
            raise ProviderError(
                f"Нет связи с провайдером ({settings.provider_host or 'адрес не задан'})"
            ) from None
        return self._read(response)

    def _read(self, response: object) -> Iterator[str]:
        """Yield the text of a streamed (SSE) or, as a fallback, a plain JSON answer."""
        with response:  # type: ignore[attr-defined]
            content_type = response.headers.get_content_type()  # type: ignore[attr-defined]
            if content_type == "application/json":
                try:
                    data = json.loads(response.read().decode("utf-8", "replace"))  # type: ignore[attr-defined]
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
                        continue  # keep-alive or a provider-specific event
                    text = delta.get("content") if isinstance(delta, dict) else None
                    if text:
                        yield str(text)
            except (TimeoutError, OSError):
                raise ProviderError("Связь с провайдером оборвалась") from None

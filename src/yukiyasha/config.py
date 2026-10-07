"""Application configuration."""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from yukiyasha.version import get_version


def _default_home() -> Path:
    configured = os.getenv("YUKIYASHA_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".yukiyasha").resolve()


def _default_disk_dir() -> Path:
    configured = os.getenv("YUKIYASHA_DISK_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return _default_home() / "disk"


LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _read_env_file(path: Path) -> dict[str, str]:
    """Parse a simple ``KEY=VALUE`` file (comments and blank lines allowed)."""
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return values
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("\"'")
    return values


def _positive_int(raw: str | None, default: int) -> int:
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


@dataclass(frozen=True, slots=True)
class AiSettings:
    """Connection to an OpenAI-compatible chat API (cloud or local).

    The API key lives only in the environment or in a file outside the repository; it is never
    written to the disk module, logged, or returned by the API (``repr=False`` below).
    """

    base_url: str = ""
    model: str = ""
    api_key: str = field(default="", repr=False)
    timeout: float = 120.0
    max_tokens: int = 2048
    max_context_chars: int = 24_000
    assistant_name: str = "Помощник"

    @property
    def problem(self) -> str | None:
        """Why the assistant cannot be used yet, in words the user can act on."""
        if not (self.base_url or self.model or self.api_key):
            return "ИИ не настроен: укажите адрес API, модель и ключ"
        missing = [
            name
            for name, value in (
                ("YUKIYASHA_AI_BASE_URL", self.base_url),
                ("YUKIYASHA_AI_MODEL", self.model),
                ("YUKIYASHA_AI_API_KEY", self.api_key),
            )
            if not value
        ]
        if missing:
            return f"Не заданы настройки: {', '.join(missing)}"
        parts = urlsplit(self.base_url)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            return "Адрес API должен начинаться с https://"
        if parts.scheme == "http" and parts.hostname not in LOCAL_HOSTS:
            return "Незащищённый адрес http:// разрешён только для localhost; используйте https://"
        return None

    @property
    def configured(self) -> bool:
        return self.problem is None

    @property
    def provider_host(self) -> str | None:
        return urlsplit(self.base_url).hostname if self.base_url else None

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "AiSettings":
        """Environment variables win over the optional ``ai.env`` file in the Yukiyasha home."""
        env = os.environ if environ is None else environ
        configured_file = env.get("YUKIYASHA_AI_ENV_FILE")
        file_values = _read_env_file(
            Path(configured_file).expanduser() if configured_file else _default_home() / "ai.env"
        )

        def get(name: str) -> str:
            return (env.get(name) or file_values.get(name) or "").strip()

        return cls(
            base_url=get("YUKIYASHA_AI_BASE_URL"),
            model=get("YUKIYASHA_AI_MODEL"),
            api_key=get("YUKIYASHA_AI_API_KEY"),
            timeout=float(_positive_int(get("YUKIYASHA_AI_TIMEOUT"), 120)),
            max_tokens=_positive_int(get("YUKIYASHA_AI_MAX_TOKENS"), 2048),
            max_context_chars=_positive_int(get("YUKIYASHA_AI_MAX_CONTEXT_CHARS"), 24_000),
            assistant_name=get("YUKIYASHA_AI_NAME") or "Помощник",
        )


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str = "Yukiyasha"
    version: str = field(default_factory=get_version)
    environment: str = "development"
    debug: bool = False
    disk_dir: Path = field(default_factory=_default_disk_dir)
    # Disabled unless built from the environment, so tests never pick up a real key.
    ai: AiSettings = field(default_factory=AiSettings)

    @classmethod
    def from_env(cls) -> "Settings":
        debug_value = os.getenv("YUKIYASHA_DEBUG", "false").strip().lower()
        return cls(
            environment=os.getenv("YUKIYASHA_ENV", "development"),
            debug=debug_value in {"1", "true", "yes", "on"},
            disk_dir=_default_disk_dir(),
            ai=AiSettings.from_env(),
        )

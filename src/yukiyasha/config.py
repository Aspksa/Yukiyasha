"""Application configuration."""

import os
from dataclasses import dataclass, field
from pathlib import Path

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


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str = "Yukiyasha"
    version: str = field(default_factory=get_version)
    environment: str = "development"
    debug: bool = False
    disk_dir: Path = field(default_factory=_default_disk_dir)

    @classmethod
    def from_env(cls) -> "Settings":
        debug_value = os.getenv("YUKIYASHA_DEBUG", "false").strip().lower()
        return cls(
            environment=os.getenv("YUKIYASHA_ENV", "development"),
            debug=debug_value in {"1", "true", "yes", "on"},
            disk_dir=_default_disk_dir(),
        )

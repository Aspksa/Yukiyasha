"""Application configuration."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str = "Yukiyasha"
    version: str = "0.2.0"
    environment: str = "development"
    debug: bool = False
    disk_dir: Path = Path("data/disk")

    @classmethod
    def from_env(cls) -> "Settings":
        debug_value = os.getenv("YUKIYASHA_DEBUG", "false").strip().lower()
        return cls(
            environment=os.getenv("YUKIYASHA_ENV", "development"),
            debug=debug_value in {"1", "true", "yes", "on"},
            disk_dir=Path(os.getenv("YUKIYASHA_DISK_DIR", "data/disk")),
        )

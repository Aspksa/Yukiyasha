"""Application configuration."""

from dataclasses import dataclass
import os


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str = "Yukiyasha"
    version: str = "0.1.0"
    environment: str = "development"
    debug: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        debug_value = os.getenv("YUKIYASHA_DEBUG", "false").strip().lower()
        return cls(
            environment=os.getenv("YUKIYASHA_ENV", "development"),
            debug=debug_value in {"1", "true", "yes", "on"},
        )

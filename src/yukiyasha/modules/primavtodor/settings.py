"""Module-wide settings of Примавтодор (currently the active fuel-norm season).

Stored as ``projects/work/Примавтодор/settings.json`` so it survives restarts and can be read
with ordinary tools. Until someone switches the season by hand, it follows the calendar.
"""

import json
from datetime import UTC, date, datetime

from yukiyasha.modules.disk import DiskError, DiskModule
from yukiyasha.modules.primavtodor.errors import RecordValidationError
from yukiyasha.modules.primavtodor.sections import PRIMAVTODOR_DIR

SEASONS: tuple[tuple[str, str], ...] = (("summer", "Лето"), ("winter", "Зима"))
SEASON_VALUES = {value for value, _ in SEASONS}
SEASON_LABELS = dict(SEASONS)
WINTER_MONTHS = {11, 12, 1, 2, 3}  # calendar default only; the switch overrides it

SETTINGS_PATH = f"{PRIMAVTODOR_DIR}/settings.json"


def default_season(today: date | None = None) -> str:
    return "winter" if (today or date.today()).month in WINTER_MONTHS else "summer"


class ModuleSettings:
    def __init__(self, disk: DiskModule) -> None:
        self._disk = disk

    def load(self) -> dict[str, object]:
        """Current season plus where it comes from ("manual" switch or the calendar)."""
        stored: dict[str, object] = {}
        try:
            data = json.loads(self._disk.read_text(SETTINGS_PATH))
            if isinstance(data, dict):
                stored = data
        except (FileNotFoundError, ValueError, DiskError):
            pass
        season = stored.get("season")
        if season in SEASON_VALUES:
            source, updated_at = "manual", stored.get("updated_at")
        else:
            season, source, updated_at = default_season(), "calendar", None
        return {
            "season": season,
            "season_label": SEASON_LABELS[str(season)],
            "source": source,
            "updated_at": updated_at,
        }

    def season(self) -> str:
        return str(self.load()["season"])

    def set_season(self, season: str) -> dict[str, object]:
        if season not in SEASON_VALUES:
            raise RecordValidationError({"season": "Выберите «Лето» или «Зима»"})
        now = datetime.now(UTC).isoformat(timespec="seconds")
        text = json.dumps({"season": season, "updated_at": now}, ensure_ascii=False, indent=2)
        self._disk.write_text(SETTINGS_PATH, text + "\n", overwrite=True)
        return self.load()

"""Module-wide settings of Примавтодор: the active fuel-norm season and the printing data.

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


CONTROL_MODES: tuple[tuple[str, str], ...] = (("mechanic", "Механик"), ("controller", "Контролёр"))
CONTROL_VALUES = {value for value, _ in CONTROL_MODES}
PRINT_TEXT_LIMIT = 300

# What the printed waybill needs besides the records: the organisation, who signs and the
# wording of the pre-trip control. Every field is optional text; empty prints an empty line.
PRINT_FIELDS: tuple[tuple[str, str], ...] = (
    ("org_name", "Организация"),
    ("org_header", "Шапка: наименование, адрес, телефон"),
    ("unit", "В распоряжение (подразделение)"),
    ("unit_name", "Структурное подразделение (табель)"),
    ("address", "Адрес подачи"),
    ("mechanic", "Механик / контролёр (ФИО)"),
    ("dispatcher", "Диспетчер-нарядчик (ФИО)"),
    ("approver_title", "Руководитель подразделения — должность"),
    ("approver", "Руководитель — ФИО"),
    ("composer_title", "Составил (ответственное лицо) — должность"),
    ("composer", "Составил — ФИО"),
)
PRINT_KEYS = {key for key, _ in PRINT_FIELDS}
DEFAULT_PRINT: dict[str, str] = {key: "" for key, _ in PRINT_FIELDS} | {"control": "mechanic"}


def default_season(today: date | None = None) -> str:
    return "winter" if (today or date.today()).month in WINTER_MONTHS else "summer"


class ModuleSettings:
    def __init__(self, disk: DiskModule) -> None:
        self._disk = disk

    def _stored(self) -> dict[str, object]:
        try:
            data = json.loads(self._disk.read_text(SETTINGS_PATH))
        except (FileNotFoundError, ValueError, DiskError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, stored: dict[str, object], stamp: str) -> None:
        stored[stamp] = datetime.now(UTC).isoformat(timespec="seconds")
        text = json.dumps(stored, ensure_ascii=False, indent=2)
        self._disk.write_text(SETTINGS_PATH, text + "\n", overwrite=True)

    def load(self) -> dict[str, object]:
        """Current season plus where it comes from ("manual" switch or the calendar)."""
        stored = self._stored()
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
        stored = self._stored()
        stored["season"] = season
        self._write(stored, "updated_at")
        return self.load()

    # ----- printing data -----

    def print_settings(self) -> dict[str, str]:
        raw = self._stored().get("print")
        raw = raw if isinstance(raw, dict) else {}
        result = dict(DEFAULT_PRINT)
        for key in PRINT_KEYS:
            if isinstance(raw.get(key), str):
                result[key] = raw[key]
        if raw.get("control") in CONTROL_VALUES:
            result["control"] = str(raw["control"])
        return result

    def set_print_settings(self, payload: dict[str, object]) -> dict[str, str]:
        errors: dict[str, str] = {}
        values: dict[str, str] = {}
        for key in PRINT_KEYS:
            raw = payload.get(key, "")
            text = " ".join(str(raw).split()) if raw is not None else ""
            if len(text) > PRINT_TEXT_LIMIT:
                errors[key] = f"Не длиннее {PRINT_TEXT_LIMIT} символов"
            values[key] = text
        control = payload.get("control", "mechanic")
        if control not in CONTROL_VALUES:
            errors["control"] = "Выберите «Механик» или «Контролёр»"
        if errors:
            raise RecordValidationError(errors)
        stored = self._stored()
        stored["print"] = {**values, "control": str(control)}
        self._write(stored, "print_updated_at")
        return self.print_settings()

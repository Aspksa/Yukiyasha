"""Structured records (employees, vehicles, waybills, fuel) stored as JSON files on the disk.

One file per record under the section folder, e.g.
``projects/work/Примавтодор/Путевые листы/wb-1a2b3c4d.json``. The files are plain, readable
JSON, so they can also be inspected or backed up with ordinary tools. All I/O goes through the
disk module's public API, so every disk safeguard (sandbox, size limit, atomic writes) applies.
"""

import json
import math
import re
import uuid
from datetime import UTC, date, datetime

from yukiyasha.modules.disk import DiskConflictError, DiskError, DiskModule
from yukiyasha.modules.primavtodor.errors import (
    RecordInUseError,
    RecordNotFoundError,
    RecordValidationError,
    UnknownEntityError,
)
from yukiyasha.modules.primavtodor.schema import (
    BOOL,
    CHOICE,
    DATE,
    ENTITIES,
    FLOAT,
    INT,
    KIND_EMPLOYEES,
    KIND_FUEL,
    KIND_VEHICLES,
    KIND_WAYBILLS,
    REF,
    TEXT,
    Entity,
    Field,
)
from yukiyasha.modules.primavtodor.sections import SECTIONS_BY_ID

ID_RE = re.compile(r"^[a-z]+-[0-9a-f]{8}$")
META_KEYS = {"id", "created_at", "updated_at"}
OVERRUN_RATIO = 0.10  # fuel consumption above the norm by more than this is flagged
MISSING_TARGET = "— удалено —"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _blank(raw: object) -> bool:
    return raw is None or (isinstance(raw, str) and not raw.strip())


def _num(value: object) -> float | None:
    """A finite number from a stored value, or None (hand-edited files may hold anything)."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) else None


def _round(value: float, digits: int = 2) -> float:
    return round(value + 0.0, digits)


def format_date(value: object) -> str:
    try:
        return date.fromisoformat(str(value)).strftime("%d.%m.%Y")
    except ValueError:
        return str(value)


class RecordStore:
    """JSON files of one record kind inside its section folder."""

    def __init__(self, disk: DiskModule, entity: Entity) -> None:
        self._disk = disk
        self.entity = entity
        self._dir = SECTIONS_BY_ID[entity.section_id].path

    def new_id(self) -> str:
        return f"{self.entity.id_prefix}-{uuid.uuid4().hex[:8]}"

    def _path(self, record_id: str) -> str:
        if not ID_RE.match(record_id) or not record_id.startswith(f"{self.entity.id_prefix}-"):
            raise RecordNotFoundError(record_id)
        return f"{self._dir}/{record_id}.json"

    @staticmethod
    def _parse(text: str, record_id: str) -> dict[str, object]:
        data = json.loads(text)
        if not isinstance(data, dict) or data.get("id") != record_id:
            raise ValueError("record id does not match its file name")
        return data

    def load_all(self) -> tuple[list[dict[str, object]], list[str]]:
        """All readable records plus the names of files that could not be read."""
        records: list[dict[str, object]] = []
        problems: list[str] = []
        prefix = f"{self.entity.id_prefix}-"
        for entry in self._disk.list_entries(self._dir):
            name = str(entry["name"])
            stem = name.removesuffix(".json")
            if entry["type"] != "file" or not name.endswith(".json"):
                continue
            if not (stem.startswith(prefix) and ID_RE.match(stem)):
                continue  # user's own file in the folder, not a record
            try:
                records.append(self._parse(self._disk.read_text(f"{self._dir}/{name}"), stem))
            except (ValueError, DiskError):
                problems.append(name)
        return records, problems

    def load(self, record_id: str) -> dict[str, object]:
        path = self._path(record_id)
        try:
            return self._parse(self._disk.read_text(path), record_id)
        except FileNotFoundError as exc:
            raise RecordNotFoundError(record_id) from exc
        except (ValueError, DiskError) as exc:
            raise RecordNotFoundError(record_id) from exc

    def save(self, record: dict[str, object], *, overwrite: bool) -> None:
        text = json.dumps(record, ensure_ascii=False, indent=2) + "\n"
        self._disk.write_text(self._path(str(record["id"])), text, overwrite=overwrite)

    def delete(self, record_id: str) -> None:
        try:
            self._disk.delete(self._path(record_id))
        except FileNotFoundError as exc:
            raise RecordNotFoundError(record_id) from exc


class _Ctx:
    """Per-request cache of all records, so relations are resolved with one read per kind."""

    def __init__(self, stores: dict[str, RecordStore]) -> None:
        self._stores = stores
        self._cache: dict[str, dict[str, dict[str, object]]] = {}

    def all(self, kind: str) -> dict[str, dict[str, object]]:
        if kind not in self._cache:
            records, _ = self._stores[kind].load_all()
            self._cache[kind] = {str(record["id"]): record for record in records}
        return self._cache[kind]

    def get(self, kind: str, record_id: object) -> dict[str, object] | None:
        return self.all(kind).get(str(record_id)) if record_id else None


class Records:
    """CRUD with validation and relation checks for the Примавтодор record kinds."""

    def __init__(self, disk: DiskModule) -> None:
        self._stores = {kind: RecordStore(disk, entity) for kind, entity in ENTITIES.items()}

    # ----- public API -----

    def schema(self) -> list[dict[str, object]]:
        return [entity.to_dict() for entity in ENTITIES.values()]

    def entity(self, kind: str) -> Entity:
        try:
            return ENTITIES[kind]
        except KeyError as exc:
            raise UnknownEntityError(f"Unknown record kind: {kind}") from exc

    def snapshot(self, kind: str) -> list[dict[str, object]]:
        """Raw stored records of a kind (for other parts of the module, e.g. the timesheet)."""
        self.entity(kind)
        return list(_Ctx(self._stores).all(kind).values())

    def list_records(self, kind: str) -> dict[str, object]:
        entity = self.entity(kind)
        records, problems = self._stores[kind].load_all()
        ctx = _Ctx(self._stores)
        records.sort(
            key=lambda record: self._sort_key(kind, record),
            reverse=kind in (KIND_WAYBILLS, KIND_FUEL),
        )
        return {
            "kind": kind,
            "records": [self._view(entity, record, ctx) for record in records],
            "problems": problems,
        }

    def get(self, kind: str, record_id: str) -> dict[str, object]:
        entity = self.entity(kind)
        return self._view(entity, self._stores[kind].load(record_id), _Ctx(self._stores))

    def create(self, kind: str, payload: dict[str, object]) -> dict[str, object]:
        entity = self.entity(kind)
        store = self._stores[kind]
        values = self._clean(entity, payload, _Ctx(self._stores), own_id=None)
        now = _now()
        record = {"id": store.new_id(), "created_at": now, "updated_at": now, **values}
        try:
            store.save(record, overwrite=False)
        except DiskConflictError:  # an id collision is practically impossible; retry once
            record["id"] = store.new_id()
            store.save(record, overwrite=False)
        return self._view(entity, record, _Ctx(self._stores))

    def update(self, kind: str, record_id: str, payload: dict[str, object]) -> dict[str, object]:
        entity = self.entity(kind)
        store = self._stores[kind]
        existing = store.load(record_id)
        values = self._clean(entity, payload, _Ctx(self._stores), own_id=record_id)
        record = {
            "id": record_id,
            "created_at": existing.get("created_at") or _now(),
            "updated_at": _now(),
            **values,
        }
        store.save(record, overwrite=True)
        return self._view(entity, record, _Ctx(self._stores))

    def delete(self, kind: str, record_id: str) -> None:
        self.entity(kind)
        store = self._stores[kind]
        store.load(record_id)  # NotFound if it does not exist
        references = self._references(kind, record_id, _Ctx(self._stores))
        if references:
            shown = ", ".join(references[:5]) + (" …" if len(references) > 5 else "")
            raise RecordInUseError(
                f"Нельзя удалить: на запись ссылаются другие данные ({shown})", references
            )
        store.delete(record_id)

    # ----- validation -----

    def _clean(
        self, entity: Entity, payload: dict[str, object], ctx: _Ctx, own_id: str | None
    ) -> dict[str, object]:
        errors: dict[str, str] = {}
        values: dict[str, object] = {}
        for item in entity.fields:
            values[item.name] = self._parse(item, payload.get(item.name), errors)
        self._normalize(entity.kind, values)
        self._check_unique(entity, values, ctx, own_id, errors)
        self._check_refs(entity, values, ctx, errors)
        if not errors:
            rule = {
                KIND_EMPLOYEES: self._rule_employee,
                KIND_VEHICLES: self._rule_vehicle,
                KIND_WAYBILLS: self._rule_waybill,
                KIND_FUEL: self._rule_fuel,
            }[entity.kind]
            rule(values, ctx, errors)
        if errors:
            raise RecordValidationError(errors)
        return values

    @staticmethod
    def _parse(item: Field, raw: object, errors: dict[str, str]) -> object:
        name = item.name
        if item.type == BOOL:
            if _blank(raw):
                return bool(item.default)
            if isinstance(raw, bool):
                return raw
            if isinstance(raw, str) and raw.strip().lower() in {"true", "1", "on", "yes"}:
                return True
            if isinstance(raw, str) and raw.strip().lower() in {"false", "0", "off", "no"}:
                return False
            errors[name] = "Допустимо только «да» или «нет»"
            return bool(item.default)

        if _blank(raw):
            if item.required:
                errors[name] = "Обязательное поле"
                return None
            return item.default

        if item.type in (TEXT, REF):
            if not isinstance(raw, str | int | float) or isinstance(raw, bool):
                errors[name] = "Введите текст"
                return None
            text = str(raw).strip() if item.multiline else " ".join(str(raw).split())
            if len(text) > item.max_len:
                errors[name] = f"Слишком длинно: не больше {item.max_len} символов"
                return None
            return text

        if item.type in (INT, FLOAT):
            number = Records._parse_number(item, raw, errors)
            if number is None:
                return None
            if item.min is not None and number < item.min:
                errors[name] = f"Не меньше {item.min:g}"
                return None
            if item.max is not None and number > item.max:
                errors[name] = f"Не больше {item.max:g}"
                return None
            return number

        if item.type == DATE:
            try:
                parsed = date.fromisoformat(str(raw).strip())
            except ValueError:
                errors[name] = "Введите дату в формате ГГГГ-ММ-ДД"
                return None
            if not 2000 <= parsed.year <= 2100:
                errors[name] = "Год должен быть между 2000 и 2100"
                return None
            return parsed.isoformat()

        if item.type == CHOICE:
            allowed = {value for value, _ in item.options}
            if str(raw).strip() not in allowed:
                errors[name] = "Выберите значение из списка"
                return None
            return str(raw).strip()

        errors[name] = "Неподдерживаемый тип поля"  # pragma: no cover - schema bug
        return None

    @staticmethod
    def _parse_number(item: Field, raw: object, errors: dict[str, str]) -> int | float | None:
        name = item.name
        value: float
        if isinstance(raw, bool):
            errors[name] = "Введите число"
            return None
        if isinstance(raw, int | float):
            value = float(raw)
        elif isinstance(raw, str):
            cleaned = raw.strip().replace(" ", "").replace(" ", "").replace(",", ".")
            try:
                value = float(cleaned)
            except ValueError:
                errors[name] = "Введите число"
                return None
        else:
            errors[name] = "Введите число"
            return None
        if not math.isfinite(value):
            errors[name] = "Введите число"
            return None
        if item.type == INT:
            if not value.is_integer():
                errors[name] = "Введите целое число"
                return None
            return int(value)
        return round(value, 3)

    @staticmethod
    def _normalize(kind: str, values: dict[str, object]) -> None:
        if kind == KIND_VEHICLES and isinstance(values.get("plate"), str):
            values["plate"] = re.sub(r"\s+", "", str(values["plate"])).upper()
        if kind == KIND_EMPLOYEES and isinstance(values.get("fuel_card_number"), str):
            values["fuel_card_number"] = re.sub(r"\s+", "", str(values["fuel_card_number"]))

    @staticmethod
    def _check_unique(
        entity: Entity,
        values: dict[str, object],
        ctx: _Ctx,
        own_id: str | None,
        errors: dict[str, str],
    ) -> None:
        for item in entity.fields:
            value = values.get(item.name)
            if not item.unique or not value or item.name in errors:
                continue
            wanted = str(value).casefold()
            for other_id, other in ctx.all(entity.kind).items():
                if other_id != own_id and str(other.get(item.name, "")).casefold() == wanted:
                    errors[item.name] = f"Уже есть запись с таким значением: «{value}»"
                    break

    def _check_refs(
        self, entity: Entity, values: dict[str, object], ctx: _Ctx, errors: dict[str, str]
    ) -> None:
        for item in entity.fields:
            value = values.get(item.name)
            if item.type != REF or not value or item.name in errors:
                continue
            assert item.ref is not None
            target = ctx.get(item.ref, value)
            if target is None:
                errors[item.name] = "Запись не найдена — выберите из списка"
            elif item.ref_filter and not target.get(item.ref_filter):
                label = ENTITIES[item.ref].field(item.ref_filter).label
                errors[item.name] = f"Подойдёт только запись с отметкой «{label}»"

    # ----- cross-field rules -----

    @staticmethod
    def _rule_employee(values: dict[str, object], ctx: _Ctx, errors: dict[str, str]) -> None:
        if not values.get("is_driver"):
            if values.get("fuel_card_number"):
                errors["fuel_card_number"] = "Топливная карта закрепляется только за водителем"
            if values.get("vehicle_id"):
                errors["vehicle_id"] = "Машина закрепляется только за водителем"

    @staticmethod
    def _rule_vehicle(values: dict[str, object], ctx: _Ctx, errors: dict[str, str]) -> None:
        return None

    @staticmethod
    def _rule_waybill(values: dict[str, object], ctx: _Ctx, errors: dict[str, str]) -> None:
        odometer_in, fuel_in = values.get("odometer_in"), values.get("fuel_in")
        if (odometer_in is None) != (fuel_in is None):
            message = "Для закрытия листа укажите и пробег, и остаток топлива при возврате"
            errors["odometer_in" if odometer_in is None else "fuel_in"] = message
        odometer_out = values.get("odometer_out")
        if (
            isinstance(odometer_in, int)
            and isinstance(odometer_out, int)
            and odometer_in < odometer_out
        ):
            errors["odometer_in"] = "Не меньше показания при выезде"

    @staticmethod
    def _rule_fuel(values: dict[str, object], ctx: _Ctx, errors: dict[str, str]) -> None:
        liters = _num(values.get("liters"))
        if liters is not None and liters <= 0:
            errors["liters"] = "Количество должно быть больше нуля"
        waybill = ctx.get(KIND_WAYBILLS, values.get("waybill_id"))
        if waybill is None:
            return
        driver = ctx.get(KIND_EMPLOYEES, waybill.get("driver_id"))
        card = str(driver.get("fuel_card_number") or "") if driver else ""
        if not card:
            name = driver.get("full_name") if driver else "водителя"
            errors["waybill_id"] = f"У водителя «{name}» не закреплена топливная карта"
            return
        vehicle = ctx.get(KIND_VEHICLES, waybill.get("vehicle_id"))
        # Derived from the waybill, so a fuel record can never contradict it.
        values["driver_id"] = waybill.get("driver_id")
        values["vehicle_id"] = waybill.get("vehicle_id")
        values["card_number"] = card
        if not values.get("fuel_type") and vehicle:
            values["fuel_type"] = vehicle.get("fuel_type")

    # ----- relations on delete -----

    def _references(self, kind: str, record_id: str, ctx: _Ctx) -> list[str]:
        found: list[str] = []
        if kind == KIND_EMPLOYEES:
            for waybill in ctx.all(KIND_WAYBILLS).values():
                if waybill.get("driver_id") == record_id:
                    found.append(self._label(KIND_WAYBILLS, waybill, ctx))
        elif kind == KIND_VEHICLES:
            for employee in ctx.all(KIND_EMPLOYEES).values():
                if employee.get("vehicle_id") == record_id:
                    found.append(f"водитель {employee.get('full_name')}")
            for waybill in ctx.all(KIND_WAYBILLS).values():
                if waybill.get("vehicle_id") == record_id:
                    found.append(self._label(KIND_WAYBILLS, waybill, ctx))
        elif kind == KIND_WAYBILLS:
            for fuel in ctx.all(KIND_FUEL).values():
                if fuel.get("waybill_id") == record_id:
                    found.append(f"заправка {format_date(fuel.get('date'))}")
        return found

    # ----- presentation -----

    @staticmethod
    def _sort_key(kind: str, record: dict[str, object]) -> tuple[str, str]:
        if kind in (KIND_WAYBILLS, KIND_FUEL):  # the caller lists these newest first
            return (str(record.get("date", "")), str(record.get("id")))
        key = "full_name" if kind == KIND_EMPLOYEES else "plate"
        return (str(record.get(key, "")).casefold(), str(record.get("id")))

    def _label(self, kind: str, record: dict[str, object], ctx: _Ctx) -> str:
        if kind == KIND_EMPLOYEES:
            return str(record.get("full_name", ""))
        if kind == KIND_VEHICLES:
            return f"{record.get('plate', '')} · {record.get('model', '')}"
        if kind == KIND_WAYBILLS:
            return f"№ {record.get('number', '')} от {format_date(record.get('date'))}"
        liters = _num(record.get("liters"))
        shown = f"{liters:g} л" if liters is not None else "заправка"
        return f"{shown} · {format_date(record.get('date'))}"

    def _view(self, entity: Entity, record: dict[str, object], ctx: _Ctx) -> dict[str, object]:
        values = {key: value for key, value in record.items() if key not in META_KEYS}
        labels: dict[str, str] = {}
        for item in entity.fields:
            if item.type == REF and values.get(item.name) and item.ref:
                target = ctx.get(item.ref, values[item.name])
                labels[item.name] = self._label(item.ref, target, ctx) if target else MISSING_TARGET
        computed, warnings = self._compute(entity.kind, record, ctx)
        return {
            "id": record["id"],
            "kind": entity.kind,
            "label": self._label(entity.kind, record, ctx),
            "values": values,
            "labels": labels,
            "computed": computed,
            "warnings": warnings,
            "created_at": record.get("created_at"),
            "updated_at": record.get("updated_at"),
        }

    def _compute(
        self, kind: str, record: dict[str, object], ctx: _Ctx
    ) -> tuple[dict[str, object], list[str]]:
        warnings: list[str] = []
        computed: dict[str, object] = {}
        record_id = record["id"]

        if kind == KIND_EMPLOYEES:
            if record.get("is_driver") and record.get("active", True):
                if not record.get("fuel_card_number"):
                    warnings.append("Не закреплена топливная карта")
                if not record.get("vehicle_id"):
                    warnings.append("Не закреплена машина")

        elif kind == KIND_VEHICLES:
            drivers = [
                str(e.get("full_name"))
                for e in ctx.all(KIND_EMPLOYEES).values()
                if e.get("vehicle_id") == record_id
            ]
            computed["drivers"] = ", ".join(sorted(drivers, key=str.casefold)) or "—"

        elif kind == KIND_WAYBILLS:
            computed, warnings = self._compute_waybill(record, ctx)

        elif kind == KIND_FUEL:
            driver = ctx.get(KIND_EMPLOYEES, record.get("driver_id"))
            vehicle = ctx.get(KIND_VEHICLES, record.get("vehicle_id"))
            liters, price = _num(record.get("liters")), _num(record.get("price_per_liter"))
            computed = {
                "driver": self._label(KIND_EMPLOYEES, driver, ctx) if driver else MISSING_TARGET,
                "vehicle": self._label(KIND_VEHICLES, vehicle, ctx) if vehicle else MISSING_TARGET,
                "card_number": record.get("card_number") or "—",
                "amount": _round(liters * price) if liters is not None and price else None,
            }
        return computed, warnings

    def _compute_waybill(
        self, record: dict[str, object], ctx: _Ctx
    ) -> tuple[dict[str, object], list[str]]:
        warnings: list[str] = []
        odometer_out = _num(record.get("odometer_out"))
        odometer_in = _num(record.get("odometer_in"))
        distance = (
            int(odometer_in - odometer_out)
            if odometer_in is not None and odometer_out is not None
            else None
        )

        issued = _round(
            sum(
                _num(fuel.get("liters")) or 0.0
                for fuel in ctx.all(KIND_FUEL).values()
                if fuel.get("waybill_id") == record["id"]
            ),
            3,
        )
        fuel_out, fuel_in = _num(record.get("fuel_out")) or 0.0, _num(record.get("fuel_in"))
        closed = odometer_in is not None and fuel_in is not None
        consumption = (
            _round(fuel_out + issued - fuel_in, 3) if closed and fuel_in is not None else None
        )

        driver = ctx.get(KIND_EMPLOYEES, record.get("driver_id"))
        vehicle = ctx.get(KIND_VEHICLES, record.get("vehicle_id"))
        rate = _num(vehicle.get("norm_per_100km")) if vehicle else None
        norm = _round(distance * rate / 100, 3) if distance is not None and rate else None
        deviation = (
            _round(consumption - norm, 3) if consumption is not None and norm is not None else None
        )

        if driver is not None and not driver.get("fuel_card_number"):
            warnings.append("У водителя не закреплена топливная карта")
        assigned = driver.get("vehicle_id") if driver else None
        if assigned and assigned != record.get("vehicle_id"):
            warnings.append("Машина отличается от закреплённой за водителем")
        if consumption is not None and consumption < 0:
            warnings.append("Остаток при возврате больше, чем было топлива")
        if deviation is not None and norm and deviation > norm * OVERRUN_RATIO:
            warnings.append("Перерасход топлива больше 10% от нормы")

        computed = {
            "status": "Закрыт" if closed else "Открыт",
            "distance": distance,
            "fuel_issued": issued,
            "consumption": consumption,
            "norm": norm,
            "deviation": deviation,
            "driver_card": (driver.get("fuel_card_number") if driver else None) or "—",
        }
        return computed, warnings


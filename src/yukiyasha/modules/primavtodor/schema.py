"""Record schemas of the Примавтодор module.

The schema is the single source of truth: the backend validates against it and the browser UI
renders its forms and tables from it (``GET /api/primavtodor/schema``).

Relations (each arrow is a reference stored by record id):

    employee (driver) --vehicle_id--> vehicle           # every driver has a car
    employee (driver) --fuel_card_number               # and a fuel card with a number
    waybill  --driver_id--> employee, --vehicle_id--> vehicle
    fuel     --waybill_id--> waybill  (driver, vehicle and card number are derived from it)
    timesheet: computed from waybills (a day with a waybill is a working day) + manual marks
"""

from dataclasses import dataclass, field

TEXT = "text"
INT = "int"
FLOAT = "float"
DATE = "date"
BOOL = "bool"
CHOICE = "choice"
REF = "ref"

FUEL_TYPES: tuple[tuple[str, str], ...] = (
    ("ДТ", "ДТ (дизельное топливо)"),
    ("АИ-92", "АИ-92"),
    ("АИ-95", "АИ-95"),
    ("АИ-98", "АИ-98"),
    ("Газ", "Газ"),
)

WAYBILL_FORMS: tuple[tuple[str, str], ...] = (
    ("car", "№ 3 — легковой автомобиль"),
    ("special", "№ 3 спец. — спецавтомобиль"),
    ("truck", "№ 4-П — грузовой автомобиль"),
)

SEASONS: tuple[tuple[str, str], ...] = (("summer", "Лето"), ("winter", "Зима"))

KIND_EMPLOYEES = "employees"
KIND_VEHICLES = "vehicles"
KIND_WAYBILLS = "waybills"
KIND_FUEL = "fuel"


@dataclass(frozen=True, slots=True)
class Field:
    name: str
    label: str
    type: str
    required: bool = False
    default: object = None
    min: float | None = None
    max: float | None = None
    max_len: int = 200
    options: tuple[tuple[str, str], ...] = ()
    ref: str | None = None  # entity kind a REF field points to
    ref_filter: str | None = None  # only targets whose boolean field of this name is true
    unique: bool = False
    multiline: bool = False
    help: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "label": self.label,
            "type": self.type,
            "required": self.required,
            "default": self.default,
            "min": self.min,
            "max": self.max,
            "max_len": self.max_len,
            "options": [{"value": value, "label": label} for value, label in self.options],
            "ref": self.ref,
            "ref_filter": self.ref_filter,
            "multiline": self.multiline,
            "help": self.help,
        }


@dataclass(frozen=True, slots=True)
class Column:
    """A list column. ``key`` is looked up in labels, then computed values, then field values."""

    key: str
    label: str
    kind: str = "text"  # text | number | date | bool | badge
    unit: str = ""

    def to_dict(self) -> dict[str, object]:
        return {"key": self.key, "label": self.label, "kind": self.kind, "unit": self.unit}


@dataclass(frozen=True, slots=True)
class Entity:
    kind: str
    section_id: str  # the section whose folder holds the records
    id_prefix: str
    title: str  # plural, shown in headings
    singular: str  # "сотрудник", used in messages
    new_label: str  # button caption
    fields: tuple[Field, ...]
    columns: tuple[Column, ...]
    # computed values shown read-only in the form: (key, label, unit)
    details: tuple[tuple[str, str, str], ...] = field(default_factory=tuple)

    def field(self, name: str) -> Field:
        for item in self.fields:
            if item.name == name:
                return item
        raise KeyError(name)

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "section_id": self.section_id,
            "title": self.title,
            "singular": self.singular,
            "new_label": self.new_label,
            "fields": [item.to_dict() for item in self.fields],
            "columns": [item.to_dict() for item in self.columns],
            "details": [
                {"key": key, "label": label, "unit": unit} for key, label, unit in self.details
            ],
        }


EMPLOYEES = Entity(
    kind=KIND_EMPLOYEES,
    section_id="employees",
    id_prefix="emp",
    title="Сотрудники",
    singular="сотрудник",
    new_label="Новый сотрудник",
    fields=(
        Field("full_name", "ФИО", TEXT, required=True, max_len=120),
        Field("position", "Должность", TEXT, default="Водитель", max_len=80),
        Field("is_driver", "Водитель", BOOL, default=True,
              help="Топливная карта и машина закрепляются только за водителями"),
        Field("personnel_number", "Табельный номер", TEXT, unique=True, max_len=30),
        Field("license_number", "Водительское удостоверение №", TEXT, max_len=30,
              help="Печатается в путевом листе"),
        Field("license_class", "Класс (категории)", TEXT, max_len=20),
        Field("phone", "Телефон", TEXT, max_len=40),
        Field("fuel_card_number", "Номер топливной карты", TEXT, unique=True, max_len=40,
              help="Карта закреплена за водителем; по ней оформляются заправки"),
        Field("vehicle_id", "Закреплённая машина", REF, ref=KIND_VEHICLES),
        Field("active", "Работает", BOOL, default=True),
    ),
    columns=(
        Column("full_name", "ФИО"),
        Column("position", "Должность"),
        Column("personnel_number", "Таб. №"),
        Column("fuel_card_number", "Топливная карта"),
        Column("vehicle_id", "Машина"),
    ),
)

VEHICLES = Entity(
    kind=KIND_VEHICLES,
    section_id="garage",
    id_prefix="veh",
    title="Машины",
    singular="машина",
    new_label="Новая машина",
    fields=(
        Field("plate", "Госномер", TEXT, required=True, unique=True, max_len=15),
        Field("model", "Марка и модель", TEXT, required=True, max_len=80),
        Field("garage_number", "Гаражный номер", TEXT, max_len=20),
        Field("waybill_form", "Бланк путевого листа", CHOICE, default="car",
              options=WAYBILL_FORMS, help="Печать готова для формы № 3 (легковой автомобиль)"),
        Field("fuel_type", "Вид топлива", CHOICE, default="ДТ", options=FUEL_TYPES),
        Field("norm_summer", "Норма расхода летом, л на 100 км", FLOAT, min=0, max=500),
        Field("norm_winter", "Норма расхода зимой, л на 100 км", FLOAT, min=0, max=500,
              help="Какая норма действует сейчас, переключается одним сезонным переключателем"),
        Field("odometer_km", "Пробег, км", INT, min=0, max=10_000_000),
        Field("active", "В эксплуатации", BOOL, default=True),
    ),
    columns=(
        Column("plate", "Госномер"),
        Column("model", "Марка и модель"),
        Column("fuel_type", "Топливо"),
        Column("norm_summer", "Лето", "number", "л/100 км"),
        Column("norm_winter", "Зима", "number", "л/100 км"),
        Column("norm_active", "Действует", "number", "л/100 км"),
        Column("drivers", "Водитель"),
    ),
)

WAYBILLS = Entity(
    kind=KIND_WAYBILLS,
    section_id="waybills",
    id_prefix="wb",
    title="Путевые листы",
    singular="путевой лист",
    new_label="Новый путевой лист",
    fields=(
        Field("number", "Номер", TEXT, required=True, unique=True, max_len=30),
        Field("date", "Дата", DATE, required=True),
        Field("driver_id", "Водитель", REF, required=True, ref=KIND_EMPLOYEES,
              ref_filter="is_driver"),
        Field("vehicle_id", "Машина", REF, required=True, ref=KIND_VEHICLES),
        Field("season", "Сезон нормы", CHOICE, required=True, options=SEASONS,
              help="Норма берётся из машины на этот сезон; по умолчанию — текущий сезон"),
        Field("route", "Маршрут", TEXT, max_len=500, multiline=True),
        Field("time_out", "Время выезда", TEXT, max_len=5, help="ЧЧ:ММ, например 08:30"),
        Field("time_in", "Время возвращения", TEXT, max_len=5, help="ЧЧ:ММ"),
        Field("odometer_out", "Одометр при выезде, км", INT, required=True, min=0,
              max=10_000_000),
        Field("odometer_in", "Одометр при возврате, км", INT, min=0, max=10_000_000,
              help="Заполняется при закрытии листа"),
        Field("fuel_out", "Остаток топлива при выезде, л", FLOAT, default=0, min=0, max=5000),
        Field("fuel_in", "Остаток топлива при возврате, л", FLOAT, min=0, max=5000,
              help="Заполняется при закрытии листа"),
    ),
    columns=(
        Column("number", "№"),
        Column("date", "Дата", "date"),
        Column("driver_id", "Водитель"),
        Column("vehicle_id", "Машина"),
        Column("season_label", "Сезон", "badge"),
        Column("distance", "Пробег", "number", "км"),
        Column("fuel_issued", "Заправлено", "number", "л"),
        Column("status", "Статус", "badge"),
    ),
    details=(
        ("driver_card", "Топливная карта водителя", ""),
        ("distance", "Пробег", "км"),
        ("fuel_issued", "Заправлено по ГСМ", "л"),
        ("consumption", "Фактический расход", "л"),
        ("season_label", "Сезон нормы", ""),
        ("norm_rate", "Норма расхода", "л/100 км"),
        ("norm", "Норма по пробегу", "л"),
        ("deviation", "Отклонение от нормы", "л"),
    ),
)

FUEL = Entity(
    kind=KIND_FUEL,
    section_id="fuel",
    id_prefix="fuel",
    title="ГСМ",
    singular="заправка",
    new_label="Новая заправка",
    fields=(
        Field("waybill_id", "Путевой лист", REF, required=True, ref=KIND_WAYBILLS,
              help="Водитель, машина и топливная карта берутся из путевого листа"),
        Field("date", "Дата", DATE, required=True),
        Field("time", "Время", TEXT, max_len=8, help="ЧЧ:ММ; заполняется при загрузке выписки"),
        Field("liters", "Количество, л", FLOAT, required=True, min=0, max=5000),
        Field("price_per_liter", "Цена за литр, ₽", FLOAT, min=0, max=100_000),
        Field("fuel_type", "Вид топлива", CHOICE, options=FUEL_TYPES,
              help="Если не указан, берётся из машины"),
        Field("station", "АЗС", TEXT, max_len=120),
    ),
    columns=(
        Column("date", "Дата", "date"),
        Column("waybill_id", "Путевой лист"),
        Column("driver", "Водитель"),
        Column("card_number", "Топливная карта"),
        Column("liters", "Литры", "number", "л"),
        Column("amount", "Сумма", "number", "₽"),
    ),
    details=(
        ("driver", "Водитель", ""),
        ("vehicle", "Машина", ""),
        ("card_number", "Топливная карта", ""),
        ("amount", "Сумма", "₽"),
    ),
)

ENTITIES: dict[str, Entity] = {
    entity.kind: entity for entity in (WAYBILLS, FUEL, EMPLOYEES, VEHICLES)
}

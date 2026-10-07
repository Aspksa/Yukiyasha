"""Printable waybills: fills the blank "Типовая межотраслевая форма № 3" workbook.

The template (``forms/waybill_form3.xlsx``) is the organisation's own blank form with every
variable value removed. The sheet holds the form twice side by side (the waybill and its copy),
so each value is written to the same cell in both halves. Nothing else in the workbook is
touched: the layout, borders and the printed back side stay exactly as they were.

The module is pure (no disk, no web): it receives plain values and returns ``.xlsx`` bytes.
"""

import io
from dataclasses import dataclass, field
from datetime import date
from importlib import resources

import openpyxl
from openpyxl.utils import column_index_from_string, get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from yukiyasha.modules.primavtodor.errors import PrintNotAvailableError

COPY_OFFSET = 101  # columns between the waybill and its copy on the front sheet
MONTHS = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)  # fmt: skip
CONTROL_TEXT = {
    "mechanic": ("Выезд разрешен", "Механик"),
    "controller": ("Предрейсовый контроль тех.состояния т/с пройден", "Контролер"),
}


@dataclass(slots=True)
class WaybillForm3:
    """Everything printed on the form. Empty values leave the cell empty."""

    number: str = ""
    day: date | None = None
    plate: str = ""
    model: str = ""
    garage_number: str = ""
    driver: str = ""
    personnel_number: str = ""
    license_number: str = ""
    license_class: str = ""
    fuel_brand: str = ""
    odometer_out: int | None = None
    odometer_in: int | None = None
    time_out: str = ""
    time_in: str = ""
    fuel_out: float | None = None
    fuel_in: float | None = None
    issued: float | None = None
    norm: float | None = None
    consumption: float | None = None
    deviation: float | None = None
    org_name: str = ""
    org_header: str = ""
    unit: str = ""
    address: str = ""
    mechanic: str = ""
    dispatcher: str = ""
    control: str = "mechanic"
    extra: dict[str, str] = field(default_factory=dict)


def short_name(full_name: str) -> str:
    """«Иванов Иван Иванович» -> «Иванов И. И.»"""
    parts = full_name.split()
    if len(parts) < 2:
        return full_name.strip()
    return " ".join([parts[0], *(f"{part[0]}." for part in parts[1:3])])


def _number(value: float | int | None) -> str:
    if value is None:
        return ""
    return f"{value:.3f}".rstrip("0").rstrip(".") if isinstance(value, float) else str(value)


def _put(sheet: Worksheet, coordinate: str, value: str) -> None:
    """Write to a cell of the template; a merged range takes the value in its top-left cell."""
    for merged in sheet.merged_cells.ranges:
        if coordinate in merged:
            coordinate = merged.start_cell.coordinate
            break
    sheet[coordinate].value = value or None


def _shift(coordinate: str, offset: int) -> str:
    letters = "".join(ch for ch in coordinate if ch.isalpha())
    row = coordinate[len(letters):]
    return f"{get_column_letter(column_index_from_string(letters) + offset)}{row}"


def fill_form3(data: WaybillForm3) -> bytes:
    """Return the filled workbook as ``.xlsx`` bytes."""
    template = resources.files("yukiyasha.modules.primavtodor").joinpath(
        "forms/waybill_form3.xlsx"
    )
    try:
        workbook = openpyxl.load_workbook(io.BytesIO(template.read_bytes()))
        sheet = workbook["Лист1"]
    except (OSError, KeyError, ValueError) as exc:
        raise PrintNotAvailableError("Не удалось открыть бланк путевого листа") from exc

    control_line, control_title = CONTROL_TEXT.get(data.control, CONTROL_TEXT["mechanic"])
    day = data.day
    deviation = data.deviation or 0.0
    values: dict[str, str] = {
        "C1": data.org_header,
        "BX4": data.number,
        "AD5": f"{day.day:02d}" if day else "",
        "AI5": MONTHS[day.month - 1] if day else "",
        "AU5": str(day.year) if day else "",
        "R8": data.org_name,
        "V10": data.model,
        "AI11": data.plate,
        "BP11": data.garage_number,
        "M12": data.driver,
        "BP12": data.personnel_number,
        "S14": data.license_number,
        "BO14": data.license_class,
        "BR19": _number(data.odometer_out),
        "Q20": data.unit,
        "A22": data.org_name,
        "AU21": control_line,
        "AU22": control_title,
        "BN22": data.mechanic,
        "R26": data.address,
        "BP26": short_name(data.driver),
        "BF28": data.fuel_brand,
        "AE29": data.time_out,
        "AD31": data.dispatcher,
        "AE33": data.time_in,
        "BT33": _number(data.issued),
        "AD35": data.dispatcher,
        "BT36": _number(data.fuel_out),
        "BT37": _number(data.fuel_in),
        "BT38": _number(data.norm),
        "BT39": _number(data.consumption),
        "BT40": _number(-deviation) if deviation < 0 else "",
        "BT41": _number(deviation) if deviation > 0 else "",
        "BT44": _number(data.odometer_in),
        "AD44": short_name(data.driver),
        "BN45": data.mechanic,
    }
    for coordinate, value in values.items():
        _put(sheet, coordinate, value)
        _put(sheet, _shift(coordinate, COPY_OFFSET), value)

    workbook.properties.title = f"Путевой лист № {data.number}"
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()

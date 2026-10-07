"""Reader of the fuel-card provider's statement («Выписка по пластиковым картам»).

The statement is a sheet with one block per card: a line «Карта № <номер> Авто: …», a header
and one row per fill-up (operation, date, time, station, fuel, price, litres, amount), then
totals. Both ``.xlsx`` and the older ``.xls`` are read. The reader only turns the sheet into
plain operations; matching them to waybills happens in the module.
"""

import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import openpyxl

from yukiyasha.modules.primavtodor.errors import PrimavtodorError

CARD_RE = re.compile(r"карта\s*№\s*([\d\s]+?)\s*(?:авто|$)", re.IGNORECASE)
MAX_OPERATIONS = 5000


class StatementError(PrimavtodorError):
    """The file is not a readable fuel-card statement."""


@dataclass(frozen=True, slots=True)
class FuelOperation:
    card: str  # digits only
    day: date
    time: str  # HH:MM:SS or ""
    station: str
    fuel_type: str
    price: float | None
    liters: float
    amount: float | None
    row: int  # 1-based row in the file, for messages


def fuel_type_of(text: str) -> str:
    """Map the provider's long fuel name to one of the module's fuel types."""
    lowered = text.lower()
    for marker, value in (
        ("аи-98", "АИ-98"), ("аи-95", "АИ-95"), ("аи-92", "АИ-92"),
        ("дизел", "ДТ"), ("газ", "Газ"),
    ):  # fmt: skip
        if marker in lowered:
            return value
    return ""


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", ".").replace(" ", ""))
    except ValueError:
        return None


def _day(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value).strip(), "%d.%m.%Y").date()
    except ValueError:
        return None


def _time(value: Any) -> str:
    if hasattr(value, "strftime"):
        return str(value.strftime("%H:%M:%S"))
    text = str(value or "").strip()
    return text if re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", text) else ""


def _rows_xlsx(content: bytes) -> list[list[Any]]:
    try:
        workbook = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - any parser failure means "not a workbook"
        raise StatementError("Не удалось открыть файл как таблицу Excel (.xlsx)") from exc
    return [list(row) for row in workbook.worksheets[0].iter_rows(values_only=True)]


def _rows_xls(content: bytes) -> list[list[Any]]:
    import xlrd

    try:
        # Files from the provider carry no code page record: the text is Windows-1251.
        book = xlrd.open_workbook(file_contents=content, encoding_override="cp1251")
    except Exception as exc:  # noqa: BLE001
        raise StatementError("Не удалось открыть файл как таблицу Excel (.xls)") from exc
    sheet = book.sheet_by_index(0)

    def cell(r: int, c: int) -> Any:
        value = sheet.cell_value(r, c)
        if sheet.cell_type(r, c) == xlrd.XL_CELL_DATE:  # a real date/time cell is a serial number
            try:
                moment = xlrd.xldate_as_datetime(value, book.datemode)
            except (xlrd.XLDateError, OverflowError):
                return value
            return moment.time() if value < 1 else moment
        return value

    return [[cell(r, c) for c in range(sheet.ncols)] for r in range(sheet.nrows)]


def parse_statement(content: bytes, filename: str) -> tuple[list[FuelOperation], str]:
    """Operations of the statement and the period line («Период с … по …»)."""
    name = filename.lower()
    if name.endswith(".xls"):
        rows = _rows_xls(content)
    elif name.endswith(".xlsx"):
        rows = _rows_xlsx(content)
    else:
        raise StatementError("Загрузите файл выписки в формате .xls или .xlsx")

    operations: list[FuelOperation] = []
    period = ""
    card = ""
    for index, row in enumerate(rows, start=1):
        first = str(row[0]).strip() if row and row[0] is not None else ""
        if first.lower().startswith("период"):
            period = first
        match = CARD_RE.search(first)
        if match:
            card = re.sub(r"\s+", "", match.group(1))
            continue
        cells = row + [None] * (8 - len(row))
        day = _day(cells[1])
        liters = _float(cells[6])
        if not (card and day and liters and first.lower().startswith("отгрузка")):
            continue
        operations.append(
            FuelOperation(
                card=card,
                day=day,
                time=_time(cells[2]),
                station=" ".join(str(cells[3] or "").split()),
                fuel_type=fuel_type_of(str(cells[4] or "")),
                price=_float(cells[5]),
                liters=liters,
                amount=_float(cells[7]),
                row=index,
            )
        )
        if len(operations) > MAX_OPERATIONS:
            raise StatementError(f"В выписке больше {MAX_OPERATIONS} операций")
    if not operations:
        raise StatementError("В файле не найдено ни одной заправки (строк «Отгрузка» по картам)")
    return operations, period

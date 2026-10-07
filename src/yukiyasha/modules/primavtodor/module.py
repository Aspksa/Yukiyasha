"""Примавтодор: a work-project module.

The module owns the folder ``projects/work/Примавтодор`` on Yukiyasha Disk and one sub-folder per
section (timesheet, employees, garage, fuel, contracts, ...). It depends only on the disk
module, never on the web layer, and talks to the disk exclusively through its public API.
"""

import re
from datetime import date

from yukiyasha.modules.disk import DiskModule
from yukiyasha.modules.manifest import ModuleManifest
from yukiyasha.modules.primavtodor.errors import (
    InvalidDocumentNameError,
    PrintNotAvailableError,
    UnknownSectionError,
)
from yukiyasha.modules.primavtodor.fuel_import import import_statement
from yukiyasha.modules.primavtodor.fuelcard import FuelCard, fill_fuel_cards
from yukiyasha.modules.primavtodor.fuelreport import ReportSigners, VehicleRow, fill_fuel_report
from yukiyasha.modules.primavtodor.printing import WaybillForm3, fill_form3, short_name
from yukiyasha.modules.primavtodor.records import Records, norm_rate
from yukiyasha.modules.primavtodor.schema import (
    KIND_EMPLOYEES,
    KIND_FUEL,
    KIND_VEHICLES,
    KIND_WAYBILLS,
    WAYBILL_FORMS,
)
from yukiyasha.modules.primavtodor.sections import (
    GROUP_DOCUMENTS,
    GROUP_TITLES,
    PRIMAVTODOR_DIR,
    SECTIONS,
    SECTIONS_BY_ID,
    Section,
)
from yukiyasha.modules.primavtodor.settings import SEASONS, ModuleSettings
from yukiyasha.modules.primavtodor.timesheet import Timesheet
from yukiyasha.modules.registry import ModuleState
from yukiyasha.version import get_version

PRIMAVTODOR_MANIFEST = ModuleManifest(
    module_id="primavtodor",
    name="Примавтодор",
    version=get_version(),
    description=(
        "Рабочий проект «Примавтодор»: путевые листы, ГСМ, сотрудники с топливными картами и "
        "машинами, гараж, табель, договора, счета-оферты, служебные записки, приказы и "
        "распоряжения на Диске Yukiyasha."
    ),
    permissions=("disk.read", "disk.write", "disk.delete"),
)


class PrimavtodorModule:
    manifest = PRIMAVTODOR_MANIFEST

    def __init__(self, disk: DiskModule) -> None:
        self._disk = disk
        self.settings = ModuleSettings(disk)
        self.data = Records(disk, self.settings)  # employees, vehicles, waybills, fuel
        self.timesheet = Timesheet(disk, self.data)
        self._state = ModuleState.REGISTERED
        self._last_error: str | None = None

    @property
    def state(self) -> ModuleState:
        return self._state

    @property
    def directory(self) -> str:
        """Project folder, relative to the disk root."""
        return PRIMAVTODOR_DIR

    @property
    def sections(self) -> tuple[Section, ...]:
        return SECTIONS

    # ----- lifecycle -----

    def start(self) -> None:
        # Needs a READY disk (registered before this module). Folders that the user deleted
        # are recreated; existing folders and their files are never touched.
        self._disk.make_dir(PRIMAVTODOR_DIR)
        for section in SECTIONS:
            self._disk.make_dir(section.path)
        self._last_error = None
        self._state = ModuleState.READY

    def stop(self) -> None:
        self._state = ModuleState.STOPPED

    def fail(self, error: BaseException) -> None:
        self._last_error = str(error)
        self._state = ModuleState.FAILED

    def snapshot(self) -> dict[str, object]:
        health: dict[str, object] = {
            "status": "ok" if self.state is ModuleState.READY else self.state.value,
            "directory": self.directory,
            "sections": len(SECTIONS),
        }
        if self._last_error:
            health["error"] = self._last_error
        return {
            "manifest": self.manifest.to_dict(),
            "state": self.state.value,
            "health": health,
        }

    def schema(self) -> dict[str, object]:
        """Everything the browser needs to render forms, tables and the timesheet."""
        entities = []
        for entity in self.data.schema():
            section = SECTIONS_BY_ID[str(entity["section_id"])]
            entities.append({**entity, "path": section.path, "section_title": section.title})
        timesheet = SECTIONS_BY_ID["timesheet"]
        return {
            "entities": entities,
            "timesheet": {
                "section_id": timesheet.id,
                "title": timesheet.title,
                "path": timesheet.path,
            },
            "timesheet_codes": self.timesheet.codes(),
            "seasons": [{"value": value, "label": label} for value, label in SEASONS],
            "settings": self.settings.load(),
        }

    # ----- sections and documents (all data lives on the disk) -----

    def section(self, section_id: str) -> Section:
        try:
            return SECTIONS_BY_ID[section_id]
        except KeyError as exc:
            raise UnknownSectionError(f"Unknown section: {section_id}") from exc

    def section_summaries(self) -> list[dict[str, object]]:
        """All sections with the number of entries currently stored in each folder."""
        return [
            {
                "id": section.id,
                "title": section.title,
                "description": section.description,
                "group": section.group,
                "group_title": GROUP_TITLES[section.group],
                "path": section.path,
                "count": len(self._disk.list_entries(section.path)),
            }
            for section in SECTIONS
        ]

    def _document_section(self, section_id: str) -> Section:
        section = self.section(section_id)
        if section.group != GROUP_DOCUMENTS:
            raise UnknownSectionError(f"Not a document section: {section_id}")
        return section

    def list_documents(self, section_id: str) -> list[dict[str, object]]:
        return self._disk.list_entries(self._document_section(section_id).path)

    def document_summaries(
        self, section_id: str, *, limit: int = 10
    ) -> list[dict[str, object]]:
        section = self._document_section(section_id)
        entries = [
            entry
            for entry in self._disk.list_entries(section.path)
            if entry.get("type") == "file"
        ][: max(1, min(limit, 20))]
        return [
            {
                "section_id": section.id,
                "section_title": section.title,
                "name": entry["name"],
                "path": entry["path"],
                "size": entry.get("size"),
                "extension": str(entry["name"]).rsplit(".", 1)[-1].lower()
                if "." in str(entry["name"])
                else "",
            }
            for entry in entries
        ]

    def document_preview(
        self, section_id: str, name: str, *, max_chars: int = 700
    ) -> dict[str, object]:
        section = self._document_section(section_id)
        path = self._document_path(section_id, name)
        entries = {
            str(entry["name"]): entry
            for entry in self._disk.list_entries(section.path)
            if entry.get("type") == "file"
        }
        entry = entries.get(name)
        if entry is None:
            raise FileNotFoundError(path)
        content = self._disk.read_text(path)
        compact = " ".join(content.split())
        return {
            "section_id": section.id,
            "section_title": section.title,
            "name": name,
            "path": path,
            "size": entry.get("size"),
            "extension": name.rsplit(".", 1)[-1].lower() if "." in name else "",
            "preview": compact[: max(80, min(max_chars, 1200))],
            "truncated": len(compact) > max_chars,
        }

    def read_document(self, section_id: str, name: str) -> str:
        self._document_section(section_id)
        return self._disk.read_text(self._document_path(section_id, name))

    def write_document(
        self, section_id: str, name: str, content: str, *, overwrite: bool = True
    ) -> str:
        """Store a text document and return its disk path."""
        path = self._document_path(section_id, name)
        self._disk.write_text(path, content, overwrite=overwrite)
        return path

    def delete_document(self, section_id: str, name: str) -> None:
        self._disk.delete(self._document_path(section_id, name))

    def _document_path(self, section_id: str, name: str) -> str:
        section = self.section(section_id)
        clean = name.strip()
        if not clean or clean in {".", ".."} or "/" in clean or "\\" in clean:
            raise InvalidDocumentNameError("Document name must be a single file name")
        return f"{section.path}/{clean}"

    # ----- printing -----

    def print_waybill(self, waybill_id: str) -> tuple[bytes, str]:
        """The waybill as a filled ``.xlsx`` of the organisation's form, and a file name."""
        waybill = self.data.get(KIND_WAYBILLS, waybill_id)
        values, computed = waybill["values"], waybill["computed"]
        driver = self.data.get(KIND_EMPLOYEES, str(values.get("driver_id")))["values"]
        vehicle = self.data.get(KIND_VEHICLES, str(values.get("vehicle_id")))["values"]

        form = str(vehicle.get("waybill_form") or "car")
        if form != "car":
            title = dict(WAYBILL_FORMS).get(form, form)
            raise PrintNotAvailableError(
                f"Печать бланка «{title}» пока не готова: сейчас доступна форма № 3 "
                "(легковой автомобиль). Для этой машины выберите другой бланк или заполните "
                "лист вручную."
            )

        try:
            day = date.fromisoformat(str(values.get("date")))
        except ValueError:
            day = None
        issued = computed.get("fuel_issued")
        settings = self.settings.print_settings()
        data = WaybillForm3(
            number=str(values.get("number") or ""),
            day=day,
            plate=str(vehicle.get("plate") or ""),
            model=str(vehicle.get("model") or ""),
            garage_number=str(vehicle.get("garage_number") or ""),
            driver=str(driver.get("full_name") or ""),
            personnel_number=str(driver.get("personnel_number") or ""),
            license_number=str(driver.get("license_number") or ""),
            license_class=str(driver.get("license_class") or ""),
            fuel_brand=str(vehicle.get("fuel_type") or ""),
            odometer_out=values.get("odometer_out"),
            odometer_in=values.get("odometer_in"),
            time_out=str(values.get("time_out") or ""),
            time_in=str(values.get("time_in") or ""),
            fuel_out=values.get("fuel_out"),
            fuel_in=values.get("fuel_in"),
            issued=issued if issued else None,
            norm=computed.get("norm"),
            consumption=computed.get("consumption"),
            deviation=computed.get("deviation"),
            org_name=settings["org_name"],
            org_header=settings["org_header"],
            unit=settings["unit"],
            address=settings["address"],
            mechanic=settings["mechanic"],
            dispatcher=settings["dispatcher"],
            control=settings["control"],
        )
        number = re.sub(r'[\\/:*?"<>|\s]+', "-", data.number).strip("-") or waybill_id
        return fill_form3(data), f"Путевой лист № {number}.xlsx"

    # ----- fuel-card statement -----

    def import_fuel_statement(
        self, content: bytes, filename: str, *, apply: bool
    ) -> dict[str, object]:
        """Preview (``apply=False``) or load the provider's statement into the fuel section."""
        return import_statement(self.data, content, filename, apply=apply)

    # ----- monthly fuel card -----

    def fuel_cards(self, vehicle_id: str, month: str) -> tuple[bytes, str]:
        """The vehicle's «Карточка расхода ГСМ» for a month (``ГГГГ-ММ``): a sheet per driver."""
        try:
            first = date.fromisoformat(f"{month}-01")
        except ValueError:
            raise PrintNotAvailableError("Месяц в формате ГГГГ-ММ, например 2026-10") from None
        vehicle = self.data.get(KIND_VEHICLES, vehicle_id)["values"]
        waybills = [
            w
            for w in self.data.snapshot(KIND_WAYBILLS)
            if w.get("vehicle_id") == vehicle_id and str(w.get("date", "")).startswith(month)
        ]
        if not waybills:
            raise PrintNotAvailableError(f"За {month} нет путевых листов на эту машину")
        waybills.sort(key=lambda w: (str(w.get("date")), str(w.get("number"))))
        fuel = self.data.snapshot(KIND_FUEL)

        views = {r["id"]: r for r in self.data.list_records(KIND_WAYBILLS)["records"]}
        by_driver: dict[str, list[dict[str, object]]] = {}
        for waybill in waybills:
            by_driver.setdefault(str(waybill.get("driver_id")), []).append(waybill)

        cards: list[FuelCard] = []
        vehicle_name = f"{vehicle.get('model') or ''} {vehicle.get('plate') or ''}".strip()
        for driver_id, driver_waybills in by_driver.items():
            driver = self.data.get(KIND_EMPLOYEES, driver_id)["values"]
            ids = {w["id"] for w in driver_waybills}
            fills = sorted(
                (f for f in fuel if f.get("waybill_id") in ids),
                key=lambda f: (str(f.get("date")), str(f.get("time") or "")),
            )
            distance = consumption = 0.0
            norms: list[float] = []
            rates: set[float | None] = set()
            for waybill in driver_waybills:
                view = views[waybill["id"]]["computed"]
                if view.get("distance") is None:
                    continue  # an open waybill has no mileage or consumption yet
                distance += float(view["distance"])
                consumption += float(view.get("consumption") or 0)
                norms.append(float(view.get("norm") or 0))
                rates.add(norm_rate(vehicle, str(waybill.get("season") or "summer")))
            rate = rates.pop() if len(rates) == 1 else None
            cards.append(
                FuelCard(
                    vehicle=vehicle_name,
                    month=first,
                    driver=str(driver.get("full_name") or ""),
                    card_number=str(driver.get("fuel_card_number") or ""),
                    distance_km=int(distance),
                    opening=float(driver_waybills[0].get("fuel_out") or 0),
                    fillups=[float(f.get("liters") or 0) for f in fills],
                    consumption=consumption,
                    norm_rate=rate,
                    norm_total=None if rate is not None else sum(norms),
                )
            )
        plate = re.sub(r"\s+", "", str(vehicle.get("plate") or vehicle_id))
        return fill_fuel_cards(cards), f"Карточка ГСМ {plate} {month}.xlsx"

    # ----- monthly analysis -----

    FORM_KINDS = {"car": "легковой", "special": "спец.", "truck": "грузовой"}

    def fuel_report(self, month: str) -> tuple[bytes, str]:
        """«Анализ расхода ГСМ» for a month (``ГГГГ-ММ``): a row per vehicle with activity."""
        try:
            first = date.fromisoformat(f"{month}-01")
        except ValueError:
            raise PrintNotAvailableError("Месяц в формате ГГГГ-ММ, например 2026-10") from None
        fuel = self.data.snapshot(KIND_FUEL)
        employees = self.data.snapshot(KIND_EMPLOYEES)
        names = {e["id"]: str(e.get("full_name") or "") for e in employees}
        in_month = [
            w for w in self.data.snapshot(KIND_WAYBILLS) if str(w.get("date", "")).startswith(month)
        ]
        waybills = sorted(in_month, key=lambda w: (str(w.get("date")), str(w.get("number"))))

        views = {r["id"]: r for r in self.data.list_records(KIND_WAYBILLS)["records"]}
        rows: list[VehicleRow] = []
        for vehicle in sorted(self.data.snapshot(KIND_VEHICLES), key=lambda v: str(v.get("plate"))):
            own = [w for w in waybills if w.get("vehicle_id") == vehicle["id"]]
            if not own:
                continue
            ids = {w["id"] for w in own}
            drivers: list[str] = []
            for waybill in own:
                name = short_name(names.get(waybill.get("driver_id"), ""))
                if name and name not in drivers:
                    drivers.append(name)
            row = VehicleRow(
                plate=str(vehicle.get("plate") or ""),
                model=str(vehicle.get("model") or ""),
                kind=self.FORM_KINDS.get(str(vehicle.get("waybill_form") or "car"), "легковой"),
                drivers=", ".join(drivers) or "Нет водителя",
                petrol=str(vehicle.get("fuel_type") or "ДТ") != "ДТ",
                opening=float(own[0].get("fuel_out") or 0),
                fillups=sum(
                    float(f.get("liters") or 0) for f in fuel if f.get("waybill_id") in ids
                ),
            )
            open_count = 0
            for waybill in own:
                computed = views[waybill["id"]]["computed"]
                if computed.get("distance") is None:
                    open_count += 1
                    continue
                row.distance_km += int(computed["distance"])
                row.actual += float(computed.get("consumption") or 0)
                row.norm += float(computed.get("norm") or 0)
            notes = []
            if open_count:
                notes.append(f"открытых путевых листов: {open_count}")
            if row.norm and row.actual > row.norm * 1.10:
                notes.append(f"перерасход {row.actual - row.norm:.1f} л")
            row.note = "; ".join(notes)
            rows.append(row)

        settings = self.settings.print_settings()
        signers = ReportSigners(
            approver_title=settings["approver_title"],
            approver=settings["approver"],
            composer_title=settings["composer_title"],
            composer=settings["composer"],
        )
        return fill_fuel_report(rows, first, signers), f"Анализ расхода ГСМ {month}.xlsx"

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
from yukiyasha.modules.primavtodor.printing import WaybillForm3, fill_form3
from yukiyasha.modules.primavtodor.records import Records
from yukiyasha.modules.primavtodor.schema import (
    KIND_EMPLOYEES,
    KIND_VEHICLES,
    KIND_WAYBILLS,
    WAYBILL_FORMS,
)
from yukiyasha.modules.primavtodor.sections import (
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

    def list_documents(self, section_id: str) -> list[dict[str, object]]:
        return self._disk.list_entries(self.section(section_id).path)

    def read_document(self, section_id: str, name: str) -> str:
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

"""Примавтодор: a work-project module.

The module owns the folder ``projects/work/Примавтодор`` on Yukiyasha Disk and one sub-folder per
section (timesheet, employees, garage, fuel, contracts, ...). It depends only on the disk
module, never on the web layer, and talks to the disk exclusively through its public API.
"""

from yukiyasha.modules.disk import DiskModule
from yukiyasha.modules.manifest import ModuleManifest
from yukiyasha.modules.primavtodor.errors import (
    InvalidDocumentNameError,
    UnknownSectionError,
)
from yukiyasha.modules.primavtodor.records import Records
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

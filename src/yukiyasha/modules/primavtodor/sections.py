"""Sections of the Примавтодор module. Each section is one folder on Yukiyasha Disk."""

from dataclasses import dataclass

PRIMAVTODOR_DIR = "projects/work/Примавтодор"

GROUP_ACCOUNTING = "accounting"
GROUP_DOCUMENTS = "documents"
GROUP_TITLES = {
    GROUP_ACCOUNTING: "Учёт",
    GROUP_DOCUMENTS: "Документы",
}


@dataclass(frozen=True, slots=True)
class Section:
    id: str  # ASCII, stable: used in URLs and code
    title: str  # shown in the UI
    folder: str  # directory name on the disk
    group: str
    description: str

    @property
    def path(self) -> str:
        """Section folder relative to the disk root."""
        return f"{PRIMAVTODOR_DIR}/{self.folder}"


SECTIONS: tuple[Section, ...] = (
    Section("timesheet", "Табель", "Табель", GROUP_ACCOUNTING, "Учёт рабочего времени"),
    Section("employees", "Сотрудники", "Сотрудники", GROUP_ACCOUNTING, "Данные сотрудников"),
    Section("garage", "Гараж", "Гараж", GROUP_ACCOUNTING, "Транспорт и техника"),
    Section(
        "fuel",
        "Горюче-смазочные материалы",
        "Горюче-смазочные материалы",
        GROUP_ACCOUNTING,
        "Учёт ГСМ",
    ),
    Section("contracts", "Договора", "Договора", GROUP_DOCUMENTS, "Договоры и приложения"),
    Section(
        "invoice_offer", "Счёт-оферта", "Счёт-оферта", GROUP_DOCUMENTS, "Счета-оферты"
    ),
    Section(
        "memos",
        "Служебные записки",
        "Служебные записки",
        GROUP_DOCUMENTS,
        "Внутренние служебные записки",
    ),
    Section("orders", "Приказы", "Приказы", GROUP_DOCUMENTS, "Приказы по организации"),
    Section(
        "directives", "Распоряжения", "Распоряжения", GROUP_DOCUMENTS, "Распоряжения руководства"
    ),
)

SECTIONS_BY_ID: dict[str, Section] = {section.id: section for section in SECTIONS}

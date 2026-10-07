"""A folder for statements: drop the provider's file into «ГСМ/Входящие» and it is loaded.

Every .xls/.xlsx file there goes through the same import as the upload dialog (matching card →
driver → waybill, never creating a fill-up twice). A file whose operations were all loaded or
recognised as already loaded moves to «Обработано»; a file with operations that could not be
matched stays in the inbox with the reasons, so it can be loaded again after the cause is fixed.
"""

from collections.abc import Callable
from datetime import datetime

from yukiyasha.modules.disk import DiskError, DiskModule
from yukiyasha.modules.primavtodor.sections import SECTIONS_BY_ID

INBOX_NAME = "Входящие"
DONE_NAME = "Обработано"
EXTENSIONS = (".xls", ".xlsx")
MAX_FILES = 20  # one scan; the rest waits for the next one


def is_service_folder(section_id: str, entry: dict[str, object]) -> bool:
    """The inbox and its archive are the module's own folders, not documents of the section."""
    return (
        section_id == "fuel"
        and entry["type"] == "directory"
        and entry["name"] in (INBOX_NAME, DONE_NAME)
    )


def inbox_dir() -> str:
    return f"{SECTIONS_BY_ID['fuel'].path}/{INBOX_NAME}"


def done_dir() -> str:
    return f"{SECTIONS_BY_ID['fuel'].path}/{DONE_NAME}"


def _waiting(disk: DiskModule) -> list[dict[str, object]]:
    try:
        entries = disk.list_entries(inbox_dir())
    except (FileNotFoundError, DiskError):
        return []
    return [
        entry
        for entry in entries
        if entry["type"] == "file"
        and str(entry["name"]).lower().endswith(EXTENSIONS)
        and not str(entry["name"]).startswith("~$")  # Excel's lock file of an open workbook
    ]


def prepare(disk: DiskModule) -> None:
    """Create the folders so the person sees where to drop a file."""
    disk.make_dir(inbox_dir())


def status(disk: DiskModule) -> dict[str, object]:
    files = _waiting(disk)
    return {
        "folder": inbox_dir(),
        "waiting": [{"name": str(f["name"]), "size": f["size"]} for f in files],
    }


def _free_name(disk: DiskModule, name: str) -> str:
    taken = {str(e["name"]) for e in _safe_list(disk, done_dir())}
    if name not in taken:
        return name
    stem, dot, ext = name.rpartition(".")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{stem}-{stamp}.{ext}" if dot else f"{name}-{stamp}"


def _safe_list(disk: DiskModule, path: str) -> list[dict[str, object]]:
    try:
        return disk.list_entries(path)
    except (FileNotFoundError, DiskError):
        return []


def scan(
    disk: DiskModule, load: Callable[[bytes, str], dict[str, object]]
) -> dict[str, object]:
    """Load every waiting statement. ``load(content, filename)`` applies one statement."""
    results: list[dict[str, object]] = []
    for entry in _waiting(disk)[:MAX_FILES]:
        name = str(entry["name"])
        path = f"{inbox_dir()}/{name}"
        item: dict[str, object] = {"name": name, "status": "failed", "message": ""}
        try:
            report = load(disk.read_bytes(path), name)
        except Exception as exc:  # noqa: BLE001 - one broken file must not stop the others
            item["message"] = str(getattr(exc, "message", "") or exc) or "Файл не прочитан"
            results.append(item)
            continue
        counts = report["counts"]
        item["counts"] = counts
        item["period"] = report.get("period")
        item["liters_new"] = report.get("liters_new", 0)
        problems = int(counts["unmatched"]) + int(counts["failed"])  # type: ignore[index]
        if problems:
            item["status"] = "attention"
            reasons = sorted(
                {
                    str(op["reason"])
                    for op in report["operations"]  # type: ignore[union-attr]
                    if op["status"] in ("unmatched", "failed") and op["reason"]
                }
            )
            item["message"] = "; ".join(reasons[:3])
        else:
            item["status"] = "loaded"
            try:
                disk.move(path, f"{done_dir()}/{_free_name(disk, name)}")
            except (DiskError, OSError) as exc:  # e.g. a second scan moved it first
                item["message"] = f"Загружено, но файл не перенесён: {exc}"
        results.append(item)
    return {
        "files": results,
        "loaded": sum(int(r["counts"]["new"]) for r in results if "counts" in r),  # type: ignore[index]
    }

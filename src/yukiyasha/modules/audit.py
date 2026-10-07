"""Persistent security audit events written to Yukiyasha Disk."""

import json
import uuid
from datetime import UTC, datetime

from yukiyasha.modules.disk import DiskModule

AUDIT_DIR = "system/audit"


class AuditLog:
    """Append-only-by-filename audit log owned by the runtime, not by a module."""

    def __init__(self, disk: DiskModule) -> None:
        self._disk = disk

    def record(
        self,
        *,
        subject: str,
        action: str,
        outcome: str,
        metadata: dict[str, object] | None = None,
    ) -> None:
        now = datetime.now(UTC)
        event = {
            "id": f"audit-{uuid.uuid4().hex[:12]}",
            "at": now.isoformat(timespec="milliseconds"),
            "subject": subject,
            "action": action,
            "outcome": outcome,
            "metadata": metadata or {},
        }
        day_dir = f"{AUDIT_DIR}/{now:%Y-%m-%d}"
        self._disk.make_dir(day_dir)
        path = f"{day_dir}/{now:%H%M%S-%f}-{uuid.uuid4().hex[:8]}.json"
        self._disk.write_text(
            path,
            json.dumps(event, ensure_ascii=False, indent=2) + "\n",
            overwrite=False,
        )

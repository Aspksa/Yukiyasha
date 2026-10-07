"""Module manifest definitions."""

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class ModuleManifest:
    module_id: str
    name: str
    version: str
    description: str
    permissions: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["permissions"] = list(self.permissions)
        return payload

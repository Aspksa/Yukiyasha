"""Central capability checks for module-to-module access."""

from yukiyasha.modules.manifest import ModuleManifest


class PermissionDeniedError(PermissionError):
    """Raised when a module asks for a capability it was not granted."""


class PermissionBroker:
    """Runtime-owned, default-deny permission registry."""

    def __init__(self) -> None:
        self._grants: dict[str, frozenset[str]] = {}

    def register(self, manifest: ModuleManifest) -> None:
        if manifest.module_id in self._grants:
            raise ValueError(f"Permissions already registered: {manifest.module_id}")
        self._grants[manifest.module_id] = frozenset(manifest.permissions)

    def require(self, subject: str, permission: str) -> None:
        if permission not in self._grants.get(subject, frozenset()):
            raise PermissionDeniedError(
                f"Module {subject!r} is not allowed to use {permission!r}"
            )

    def allowed(self, subject: str, permission: str) -> bool:
        return permission in self._grants.get(subject, frozenset())

    def permissions(self, subject: str) -> tuple[str, ...]:
        return tuple(sorted(self._grants.get(subject, frozenset())))

    def snapshot(self) -> dict[str, list[str]]:
        return {subject: sorted(values) for subject, values in sorted(self._grants.items())}

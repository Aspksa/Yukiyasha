"""Module registry and lifecycle coordination."""

from enum import StrEnum
from typing import Protocol

from yukiyasha.modules.manifest import ModuleManifest


class ModuleState(StrEnum):
    REGISTERED = "registered"
    READY = "ready"
    FAILED = "failed"
    STOPPED = "stopped"


class Module(Protocol):
    manifest: ModuleManifest

    @property
    def state(self) -> ModuleState: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def fail(self, error: BaseException) -> None: ...

    def snapshot(self) -> dict[str, object]: ...


class ModuleRegistry:
    def __init__(self) -> None:
        self._modules: dict[str, Module] = {}

    def register(self, module: Module) -> None:
        module_id = module.manifest.module_id
        if not module_id or not module_id.replace("-", "").replace("_", "").isalnum():
            raise ValueError(f"Invalid module id: {module_id!r}")
        if module_id in self._modules:
            raise ValueError(f"Module already registered: {module_id}")
        self._modules[module_id] = module

    def get(self, module_id: str) -> Module:
        try:
            return self._modules[module_id]
        except KeyError as exc:
            raise KeyError(f"Unknown module: {module_id}") from exc

    def start_all(self) -> None:
        started: list[Module] = []
        for module in self._modules.values():
            try:
                module.start()
            except Exception as exc:
                try:
                    module.stop()
                except Exception:
                    pass
                module.fail(exc)

                for started_module in reversed(started):
                    try:
                        started_module.stop()
                    except Exception:
                        # Preserve the startup failure as the primary exception.
                        continue
                raise
            started.append(module)

    def stop_all(self) -> None:
        errors: list[BaseException] = []
        for module in reversed(tuple(self._modules.values())):
            try:
                module.stop()
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise ExceptionGroup("Failed to stop one or more modules", errors)

    def snapshots(self) -> list[dict[str, object]]:
        return [module.snapshot() for module in self._modules.values()]

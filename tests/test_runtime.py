from pathlib import Path

from yukiyasha.config import Settings
from yukiyasha.core.runtime import RuntimeState, YukiyashaRuntime
from yukiyasha.modules.registry import ModuleState
from yukiyasha.version import get_version


def test_runtime_lifecycle_and_restart_timestamp(tmp_path: Path) -> None:
    runtime = YukiyashaRuntime(Settings(disk_dir=tmp_path / "disk"))

    assert runtime.state is RuntimeState.STOPPED
    assert runtime.snapshot().started_at is None

    runtime.start()
    first = runtime.snapshot()

    assert first.name == "Yukiyasha"
    assert first.version == get_version()
    assert first.state is RuntimeState.READY
    assert first.started_at is not None
    assert runtime.disk.state is ModuleState.READY

    runtime.stop()
    assert runtime.state is RuntimeState.STOPPED
    assert runtime.disk.state is ModuleState.STOPPED

    runtime.start()
    second = runtime.snapshot()

    assert second.state is RuntimeState.READY
    assert second.started_at is not None
    assert second.started_at >= first.started_at


def test_runtime_stays_available_as_degraded_when_module_start_fails(
    tmp_path: Path, monkeypatch
) -> None:
    runtime = YukiyashaRuntime(Settings(disk_dir=tmp_path / "disk"))

    def fail_start() -> None:
        raise RuntimeError("disk failed")

    monkeypatch.setattr(runtime.disk, "start", fail_start)
    runtime.start()

    assert runtime.state is RuntimeState.DEGRADED
    assert runtime.disk.state is ModuleState.FAILED

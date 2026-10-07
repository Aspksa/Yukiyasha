from pathlib import Path

from yukiyasha.config import Settings
from yukiyasha.core.runtime import RuntimeState, YukiyashaRuntime
from yukiyasha.modules.registry import ModuleState


def test_runtime_lifecycle(tmp_path: Path) -> None:
    runtime = YukiyashaRuntime(Settings(disk_dir=tmp_path / "disk"))

    assert runtime.state is RuntimeState.STARTING

    runtime.start()
    snapshot = runtime.snapshot()

    assert snapshot.name == "Yukiyasha"
    assert snapshot.version == "0.2.0"
    assert snapshot.state is RuntimeState.READY
    assert runtime.disk.state is ModuleState.READY

    runtime.stop()
    assert runtime.state is RuntimeState.STOPPED
    assert runtime.disk.state is ModuleState.STOPPED

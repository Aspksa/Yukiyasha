from yukiyasha.config import Settings
from yukiyasha.core.runtime import RuntimeState, YukiyashaRuntime


def test_runtime_lifecycle() -> None:
    runtime = YukiyashaRuntime(Settings())

    assert runtime.state is RuntimeState.STARTING

    runtime.start()
    snapshot = runtime.snapshot()

    assert snapshot.name == "Yukiyasha"
    assert snapshot.version == "0.1.0"
    assert snapshot.state is RuntimeState.READY

    runtime.stop()
    assert runtime.state is RuntimeState.STOPPED

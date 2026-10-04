import pytest

from langgraph_xai import Evidence, PluginManager
from tests.helpers import RecordingPlugin, context


def test_plugins_are_validated_on_construction_and_add() -> None:
    with pytest.raises(TypeError, match="does not implement XAIPlugin"):
        PluginManager([object()])  # pyrefly: ignore[bad-argument-type]
    manager = PluginManager()
    with pytest.raises(TypeError):
        manager.add(object())  # pyrefly: ignore[bad-argument-type]

    plugin = manager.add(RecordingPlugin())

    assert manager.plugins == (plugin,)


async def test_every_plugin_receives_every_call_in_order() -> None:
    log: list[str] = []
    first, second = RecordingPlugin("first", log=log), RecordingPlugin("second", log=log)
    manager = PluginManager([first, second])
    artifact = Evidence(evidence_type="rule", context=context())

    await manager.record(artifact)
    await manager.flush()
    await manager.close()

    assert first.artifacts == second.artifacts == [artifact]
    assert log == [
        "first.record",
        "second.record",
        "first.flush",
        "second.flush",
        "second.close",
        "first.close",
    ]


async def test_one_failure_does_not_starve_other_plugins() -> None:
    log: list[str] = []
    healthy = RecordingPlugin("healthy", log=log)
    manager = PluginManager([RecordingPlugin("broken", fail=True, log=log), healthy])

    with pytest.raises(ValueError, match="broken failed"):
        await manager.close()

    assert log == ["healthy.close", "broken.close"]


async def test_multiple_failures_are_grouped() -> None:
    manager = PluginManager([RecordingPlugin("a", fail=True), RecordingPlugin("b", fail=True)])

    with pytest.raises(ExceptionGroup) as raised:
        await manager.flush()

    assert [str(error) for error in raised.value.exceptions] == ["a failed", "b failed"]

"""Instance-scoped plugin collection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import SemanticArtifact, XAIPlugin

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Iterable
    from typing import Any


class PluginManager:
    """Dispatch semantic artifacts and lifecycle calls to every registered plugin.

    Every call reaches every plugin even when one of them fails; the failures
    are then raised together (a single exception as-is, several as an
    `ExceptionGroup`) so the runtime can apply its failure mode once.
    """

    def __init__(self, plugins: Iterable[XAIPlugin] = ()) -> None:
        self._plugins: list[XAIPlugin] = []
        for plugin in plugins:
            self.add(plugin)

    @property
    def plugins(self) -> tuple[XAIPlugin, ...]:
        """The registered plugins, in registration order."""
        return tuple(self._plugins)

    def add(self, plugin: XAIPlugin) -> XAIPlugin:
        """Register ``plugin``; raises `TypeError` if it does not implement `XAIPlugin`."""
        if not isinstance(plugin, XAIPlugin):
            raise TypeError(f"{type(plugin).__name__} does not implement XAIPlugin")
        self._plugins.append(plugin)
        return plugin

    async def record(self, artifact: SemanticArtifact) -> None:
        """Deliver ``artifact`` to every plugin."""
        await _call_all(self._plugins, lambda plugin: plugin.record(artifact))

    async def flush(self) -> None:
        """Flush every plugin."""
        await _call_all(self._plugins, lambda plugin: plugin.flush())

    async def close(self) -> None:
        """Close every plugin, in reverse registration order."""
        await _call_all(reversed(self._plugins), lambda plugin: plugin.close())


async def _call_all(
    plugins: Iterable[XAIPlugin],
    call: Callable[[XAIPlugin], Coroutine[Any, Any, None]],
) -> None:
    errors: list[Exception] = []
    for plugin in plugins:
        try:
            await call(plugin)
        except Exception as error:
            errors.append(error)
    if len(errors) == 1:
        raise errors[0]
    if errors:
        raise ExceptionGroup("multiple plugins failed", errors)

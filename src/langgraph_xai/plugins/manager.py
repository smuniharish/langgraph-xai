"""Instance-scoped plugin collection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import SemanticArtifact, XAIPlugin

if TYPE_CHECKING:
    from collections.abc import Iterable


class PluginManager:
    def __init__(self, plugins: Iterable[XAIPlugin] = ()) -> None:
        self._plugins = list(plugins)

    @property
    def plugins(self) -> tuple[XAIPlugin, ...]:
        return tuple(self._plugins)

    def add(self, plugin: XAIPlugin) -> XAIPlugin:
        if not isinstance(plugin, XAIPlugin):
            raise TypeError(f"{type(plugin).__name__} does not implement XAIPlugin")
        self._plugins.append(plugin)
        return plugin

    async def record(self, artifact: SemanticArtifact) -> None:
        for plugin in self._plugins:
            await plugin.record(artifact)

    async def flush(self) -> None:
        for plugin in self._plugins:
            await plugin.flush()

    async def close(self) -> None:
        for plugin in reversed(self._plugins):
            await plugin.close()

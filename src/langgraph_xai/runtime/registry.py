"""Instance-scoped capability registry."""

from __future__ import annotations

from typing import TypeVar

Capability = TypeVar("Capability")


class Registry:
    """Map each capability protocol to the provider one runtime uses for it."""

    def __init__(self) -> None:
        self._providers: dict[type[object], object] = {}

    def register(self, capability: type[Capability], provider: Capability) -> Capability:
        """Register or replace the provider of ``capability``.

        Raises:
            TypeError: If ``provider`` does not implement ``capability``.
        """
        if not isinstance(provider, capability):
            raise TypeError(f"{type(provider).__name__} does not implement {capability.__name__}")
        self._providers[capability] = provider
        return provider

    def get(self, capability: type[Capability]) -> Capability | None:
        """Return the provider of ``capability``, or ``None`` if none is registered."""
        provider = self._providers.get(capability)
        if provider is None:
            return None
        if not isinstance(provider, capability):
            raise TypeError(f"Registered provider no longer implements {capability.__name__}")
        return provider

    def require(self, capability: type[Capability]) -> Capability:
        """Return the provider of ``capability``.

        Raises:
            LookupError: If no provider is registered.
        """
        provider = self.get(capability)
        if provider is None:
            raise LookupError(f"No provider registered for {capability.__name__}")
        return provider

    def remove(self, capability: type[Capability]) -> object | None:
        """Unregister ``capability`` and return its provider, if any."""
        return self._providers.pop(capability, None)

    def capabilities(self) -> tuple[type[object], ...]:
        """The registered capability protocols, in registration order."""
        return tuple(self._providers)

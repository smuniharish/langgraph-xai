"""No-op observability provider."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import ObservabilityAdapter

if TYPE_CHECKING:
    from ..core.models import CanonicalEvent


class NoOpObservability(ObservabilityAdapter):
    """Discard events while preserving the provider lifecycle (the default provider)."""

    def __init__(self) -> None:
        super().__init__(deduplication_window=0)

    async def _emit(self, event: CanonicalEvent) -> None:
        del event

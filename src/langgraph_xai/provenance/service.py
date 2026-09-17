"""Provider-neutral provenance query service."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ..core.models import ExecutionContext, ProvenanceLink
    from ..core.protocols import ProvenanceStore


class Provenance:
    def __init__(self, store: ProvenanceStore, context: ExecutionContext) -> None:
        self._store = store
        self._context = context

    async def parents(self, entity_id: str) -> Sequence[ProvenanceLink]:
        return await self._store.parents(entity_id, context=self._context)

    async def children(self, entity_id: str) -> Sequence[ProvenanceLink]:
        return await self._store.children(entity_id, context=self._context)

    async def lineage(
        self,
        entity_id: str,
        *,
        max_depth: int = 100,
    ) -> Sequence[ProvenanceLink]:
        return await self._store.lineage(
            entity_id,
            context=self._context,
            max_depth=max_depth,
        )

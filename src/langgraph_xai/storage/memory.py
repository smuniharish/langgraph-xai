"""Concurrency-safe in-memory provenance storage."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..core.models import (
    CanonicalEvent,
    Execution,
    ExecutionContext,
    ProvenanceLink,
    XAIEvent,
)
from ..core.protocols import StoreQuery

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

type StoredItem = Execution | ProvenanceLink | CanonicalEvent


@dataclass(frozen=True, slots=True)
class StoreFilter(StoreQuery):
    """Isolation-aware query for canonical records."""

    application_id: str
    tenant_id: str
    run_id: str | None = None
    item_type: type[StoredItem] | None = None
    limit: int = 100
    offset: int = 0

    def __post_init__(self) -> None:
        if self.limit < 1:
            raise ValueError("limit must be positive")
        if self.offset < 0:
            raise ValueError("offset must not be negative")


def _key(item: StoredItem) -> str:
    if isinstance(item, XAIEvent):
        return f"event:{item.event_id}"
    return f"{type(item).__name__}:{item.id}"


def _same_scope(left: ExecutionContext, right: ExecutionContext) -> bool:
    return (
        left.application_id == right.application_id
        and left.tenant_id == right.tenant_id
        and left.run_id == right.run_id
    )


class InMemoryProvenanceStore:
    """An isolated store suitable for tests, local use, and ephemeral runs."""

    def __init__(self) -> None:
        self._items: dict[str, StoredItem] = {}
        self._lock = asyncio.Lock()
        self._closed = False

    async def write(self, item: StoredItem) -> None:
        self._ensure_open()
        async with self._lock:
            self._items[_key(item)] = item.model_copy(deep=True)

    async def get(self, entity_id: str) -> StoredItem | None:
        self._ensure_open()
        async with self._lock:
            matches = [
                item.model_copy(deep=True)
                for key, item in self._items.items()
                if key.rsplit(":", 1)[-1] == entity_id
            ]
        if len(matches) > 1:
            raise LookupError("entity ID is ambiguous; use an isolation-aware query")
        return matches[0] if matches else None

    async def query(self, query: StoreQuery) -> AsyncIterator[StoredItem]:
        self._ensure_open()
        if not isinstance(query, StoreFilter):
            raise TypeError("InMemoryProvenanceStore requires StoreFilter")
        async with self._lock:
            items = [
                item.model_copy(deep=True)
                for item in self._items.values()
                if item.context.application_id == query.application_id
                and item.context.tenant_id == query.tenant_id
                and (query.run_id is None or str(item.context.run_id) == query.run_id)
                and (query.item_type is None or isinstance(item, query.item_type))
            ]
        items.sort(key=lambda item: (item.timestamp, str(item.id)))
        for item in items[query.offset : query.offset + query.limit]:
            yield item

    async def parents(
        self,
        entity_id: str,
        *,
        context: ExecutionContext,
    ) -> Sequence[ProvenanceLink]:
        return await self._links(entity_id, context=context, parent=True)

    async def children(
        self,
        entity_id: str,
        *,
        context: ExecutionContext,
    ) -> Sequence[ProvenanceLink]:
        return await self._links(entity_id, context=context, parent=False)

    async def lineage(
        self,
        entity_id: str,
        *,
        context: ExecutionContext,
        max_depth: int = 100,
    ) -> Sequence[ProvenanceLink]:
        if max_depth < 1:
            raise ValueError("max_depth must be positive")
        result: list[ProvenanceLink] = []
        visited = {entity_id}
        frontier = [entity_id]
        for _ in range(max_depth):
            next_frontier: list[str] = []
            for current in frontier:
                for link in await self.parents(current, context=context):
                    source = str(link.source_id)
                    if str(link.id) not in {str(item.id) for item in result}:
                        result.append(link)
                    if source not in visited:
                        visited.add(source)
                        next_frontier.append(source)
            if not next_frontier:
                break
            frontier = next_frontier
        return tuple(result)

    async def close(self) -> None:
        self._closed = True

    async def _links(
        self,
        entity_id: str,
        *,
        context: ExecutionContext,
        parent: bool,
    ) -> tuple[ProvenanceLink, ...]:
        self._ensure_open()
        async with self._lock:
            links = [
                item.model_copy(deep=True)
                for item in self._items.values()
                if isinstance(item, ProvenanceLink)
                and _same_scope(item.context, context)
                and str(item.target_id if parent else item.source_id) == entity_id
            ]
        links.sort(key=lambda item: (item.timestamp, str(item.id)))
        return tuple(links)

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("store is closed")

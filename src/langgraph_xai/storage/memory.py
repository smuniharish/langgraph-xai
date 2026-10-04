"""Thread-safe in-memory provenance storage."""

from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from ..core.models import (
    CanonicalEvent,
    Execution,
    ExecutionContext,
    ProvenanceLink,
    XAIEvent,
)
from ..core.protocols import ProvenanceStore, StoreQuery

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence
    from datetime import datetime

type StoredItem = Execution | ProvenanceLink | CanonicalEvent
type _Scope = tuple[str, str, str]
type _Endpoint = tuple[_Scope, str]


@dataclass(frozen=True, slots=True)
class StoreFilter(StoreQuery):
    """Isolation-aware query: one application and tenant, optionally one run and record type.

    ``run_id`` accepts a `UUID` or its string form and is normalized to the
    canonical string. Results are ordered by ``(timestamp, sequence, id)`` and
    paginated with ``limit``/``offset``.
    """

    application_id: str
    tenant_id: str
    run_id: str | UUID | None = None
    item_type: type[StoredItem] | None = None
    limit: int = 100
    offset: int = 0

    def __post_init__(self) -> None:
        if self.limit < 1:
            raise ValueError("limit must be positive")
        if self.offset < 0:
            raise ValueError("offset must not be negative")
        if self.run_id is not None:
            try:
                normalized = str(UUID(str(self.run_id)))
            except ValueError as exc:
                raise ValueError("run_id must be a UUID") from exc
            object.__setattr__(self, "run_id", normalized)


def record_id(item: StoredItem) -> str:
    """Return the ID a record is stored and fetched under: its ``id`` as a string."""
    return str(item.id)


def _scope(context: ExecutionContext) -> _Scope:
    return (context.application_id, context.tenant_id, str(context.run_id))


@dataclass(frozen=True, slots=True)
class _Record:
    """A stored record: its dumped data plus the fields the indexes and ordering need."""

    model: type[Execution | ProvenanceLink | XAIEvent]
    data: dict[str, Any]
    record_id: str
    tenant: tuple[str, str]
    run_id: str
    order: tuple[datetime, int, str]
    endpoints: tuple[_Endpoint, _Endpoint] | None

    @classmethod
    def of(cls, item: StoredItem) -> _Record:
        context = item.context
        endpoints = None
        if isinstance(item, ProvenanceLink):
            scope = _scope(context)
            endpoints = ((scope, str(item.target_id)), (scope, str(item.source_id)))
        return cls(
            model=type(item),
            data=item.model_dump(),
            record_id=record_id(item),
            tenant=(context.application_id, context.tenant_id),
            run_id=str(context.run_id),
            order=(item.timestamp, getattr(item, "sequence", -1), str(item.id)),
            endpoints=endpoints,
        )

    def load(self) -> StoredItem:
        return cast("StoredItem", self.model.model_validate(self.data))


class InMemoryProvenanceStore(ProvenanceStore):
    """The default store: thread-safe and indexed, for development, tests, and ephemeral runs.

    Records are serialized on write and rebuilt on read, so mutating a live
    `Execution` (or a returned record) never changes stored data, and writes
    stay cheap because validation happens only for records that are read. One
    lock protects the indexes, which makes the store safe to share across
    threads and event loops. Records are kept until the process exits.
    """

    def __init__(self) -> None:
        self._records: dict[str, _Record] = {}
        self._by_id: defaultdict[str, set[str]] = defaultdict(set)
        self._by_tenant: defaultdict[tuple[str, str], dict[str, None]] = defaultdict(dict)
        self._by_target: defaultdict[tuple[_Scope, str], dict[str, None]] = defaultdict(dict)
        self._by_source: defaultdict[tuple[_Scope, str], dict[str, None]] = defaultdict(dict)
        self._lock = threading.Lock()
        self._closed = False

    async def write(self, item: StoredItem) -> None:
        """Insert or replace ``item``; the latest write of a record wins."""
        self._ensure_open()
        record = _Record.of(item)
        key = f"{record.model.__name__}:{record.record_id}"
        with self._lock:
            previous = self._records.get(key)
            if previous is not None:
                self._unindex(key, previous)
            self._records[key] = record
            self._index(key, record)

    async def get(self, entity_id: str) -> StoredItem | None:
        """Return a copy of the record whose ``id`` is ``entity_id``, if any."""
        self._ensure_open()
        with self._lock:
            matches = [self._records[key] for key in self._by_id.get(entity_id, ())]
        if len(matches) > 1:
            raise LookupError("entity ID is ambiguous; use an isolation-aware query")
        return matches[0].load() if matches else None

    async def query(self, query: StoreQuery) -> AsyncIterator[StoredItem]:
        """Yield copies of the records matching a `StoreFilter`."""
        self._ensure_open()
        if not isinstance(query, StoreFilter):
            raise TypeError("InMemoryProvenanceStore requires StoreFilter")
        with self._lock:
            keys = self._by_tenant.get((query.application_id, query.tenant_id), {})
            records = [
                record
                for record in map(self._records.__getitem__, keys)
                if (query.run_id is None or record.run_id == query.run_id)
                and (query.item_type is None or issubclass(record.model, query.item_type))
            ]
        records.sort(key=lambda record: record.order)
        for record in records[query.offset : query.offset + query.limit]:
            yield record.load()

    async def parents(
        self,
        entity_id: str,
        *,
        context: ExecutionContext,
    ) -> Sequence[ProvenanceLink]:
        """Return the links whose target is ``entity_id`` within the context's run."""
        return self._links(self._by_target, entity_id, context)

    async def children(
        self,
        entity_id: str,
        *,
        context: ExecutionContext,
    ) -> Sequence[ProvenanceLink]:
        """Return the links whose source is ``entity_id`` within the context's run."""
        return self._links(self._by_source, entity_id, context)

    async def close(self) -> None:
        """Reject further reads and writes."""
        self._closed = True

    def _links(
        self,
        index: defaultdict[tuple[_Scope, str], dict[str, None]],
        entity_id: str,
        context: ExecutionContext,
    ) -> tuple[ProvenanceLink, ...]:
        self._ensure_open()
        with self._lock:
            records = [self._records[key] for key in index.get((_scope(context), entity_id), ())]
        records.sort(key=lambda record: record.order)
        return tuple(cast("ProvenanceLink", record.load()) for record in records)

    def _index(self, key: str, record: _Record) -> None:
        self._by_id[record.record_id].add(key)
        self._by_tenant[record.tenant][key] = None
        if record.endpoints is not None:
            target, source = record.endpoints
            self._by_target[target][key] = None
            self._by_source[source][key] = None

    def _unindex(self, key: str, record: _Record) -> None:
        _discard(self._by_id, record.record_id, key)
        _discard(self._by_tenant, record.tenant, key)
        if record.endpoints is not None:
            target, source = record.endpoints
            _discard(self._by_target, target, key)
            _discard(self._by_source, source, key)

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("store is closed")


def _discard[IndexKey](
    index: defaultdict[IndexKey, set[str]] | defaultdict[IndexKey, dict[str, None]],
    index_key: IndexKey,
    key: str,
) -> None:
    # Called under the lock for an entry that _index added, so the key exists.
    entries = index[index_key]
    if isinstance(entries, set):
        entries.remove(key)
    else:
        del entries[key]
    if not entries:
        del index[index_key]

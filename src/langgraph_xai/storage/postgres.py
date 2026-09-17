"""Optional PostgreSQL provenance store."""

from __future__ import annotations

import json
from importlib import import_module
from typing import TYPE_CHECKING, Any

from pydantic import TypeAdapter

from ..core.models import CanonicalEvent, Execution, ExecutionContext, ProvenanceLink
from .memory import StoredItem, StoreFilter

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from ..core.protocols import StoreQuery

    type AsyncConnectionPool = Any

_ITEM_ADAPTER = TypeAdapter(Execution | ProvenanceLink | CanonicalEvent)


class PostgresProvenanceStore:
    """JSONB-backed store with indexed isolation and idempotency columns."""

    def __init__(self, dsn: str, *, pool: AsyncConnectionPool | None = None) -> None:
        if pool is None:
            try:
                pool_class = import_module("psycopg_pool").AsyncConnectionPool
            except ImportError as exc:
                raise ImportError("PostgreSQL storage requires 'langgraph-xai[postgres]'") from exc
            pool = pool_class(dsn, open=False)
        if pool is None:
            raise RuntimeError("PostgreSQL connection pool could not be created")
        self._pool: Any = pool

    async def open(self) -> None:
        await self._pool.open()
        async with self._pool.connection() as connection:
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS langgraph_xai_records (
                    record_key TEXT PRIMARY KEY,
                    record_type TEXT NOT NULL,
                    application_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    run_id UUID NOT NULL,
                    timestamp TIMESTAMPTZ NOT NULL,
                    payload JSONB NOT NULL
                );
                CREATE INDEX IF NOT EXISTS langgraph_xai_scope_idx
                ON langgraph_xai_records
                    (application_id, tenant_id, run_id, timestamp);
                """
            )

    async def write(self, item: StoredItem) -> None:
        key = f"{type(item).__name__}:{getattr(item, 'event_id', item.id)}"
        async with self._pool.connection() as connection:
            await connection.execute(
                """
                INSERT INTO langgraph_xai_records
                    (record_key, record_type, application_id, tenant_id,
                     run_id, timestamp, payload)
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (record_key) DO UPDATE SET payload = EXCLUDED.payload
                """,
                (
                    key,
                    type(item).__name__,
                    item.context.application_id,
                    item.context.tenant_id,
                    item.context.run_id,
                    item.timestamp,
                    item.model_dump_json(),
                ),
            )

    async def get(self, entity_id: str) -> StoredItem | None:
        async with self._pool.connection() as connection:
            rows = await (
                await connection.execute(
                    "SELECT payload FROM langgraph_xai_records WHERE record_key LIKE %s LIMIT 2",
                    (f"%:{entity_id}",),
                )
            ).fetchall()
        if len(rows) > 1:
            raise LookupError("entity ID is ambiguous; use an isolation-aware query")
        return _ITEM_ADAPTER.validate_python(rows[0][0]) if rows else None

    async def query(self, query: StoreQuery) -> AsyncIterator[StoredItem]:
        if not isinstance(query, StoreFilter):
            raise TypeError("PostgresProvenanceStore requires StoreFilter")
        record_type = query.item_type.__name__ if query.item_type else None
        values = (
            query.application_id,
            query.tenant_id,
            query.run_id,
            query.run_id,
            record_type,
            record_type,
            query.limit,
            query.offset,
        )
        async with self._pool.connection() as connection:
            rows = await (
                await connection.execute(
                    """
                    SELECT payload FROM langgraph_xai_records
                    WHERE application_id = %s AND tenant_id = %s
                      AND (%s::uuid IS NULL OR run_id = %s::uuid)
                      AND (%s::text IS NULL OR record_type = %s::text)
                    ORDER BY timestamp, record_key LIMIT %s OFFSET %s
                    """,
                    values,
                )
            ).fetchall()
        for row in rows:
            yield _ITEM_ADAPTER.validate_python(
                json.loads(row[0]) if isinstance(row[0], str) else row[0]
            )

    async def parents(
        self,
        entity_id: str,
        *,
        context: ExecutionContext,
    ) -> Sequence[ProvenanceLink]:
        return await self._links(entity_id, context, "target_id")

    async def children(
        self,
        entity_id: str,
        *,
        context: ExecutionContext,
    ) -> Sequence[ProvenanceLink]:
        return await self._links(entity_id, context, "source_id")

    async def lineage(
        self,
        entity_id: str,
        *,
        context: ExecutionContext,
        max_depth: int = 100,
    ) -> Sequence[ProvenanceLink]:
        result: list[ProvenanceLink] = []
        frontier = [entity_id]
        visited = set(frontier)
        for _ in range(max_depth):
            next_frontier: list[str] = []
            for current in frontier:
                for link in await self.parents(current, context=context):
                    result.append(link)
                    source = str(link.source_id)
                    if source not in visited:
                        visited.add(source)
                        next_frontier.append(source)
            if not next_frontier:
                break
            frontier = next_frontier
        return tuple(result)

    async def close(self) -> None:
        await self._pool.close()

    async def _links(
        self,
        entity_id: str,
        context: ExecutionContext,
        field: str,
    ) -> tuple[ProvenanceLink, ...]:
        async with self._pool.connection() as connection:
            rows = await (
                await connection.execute(
                    """
                    SELECT payload FROM langgraph_xai_records
                    WHERE record_type = 'ProvenanceLink'
                      AND application_id = %s AND tenant_id = %s AND run_id = %s
                      AND payload->>%s = %s
                    ORDER BY timestamp, record_key
                    """,
                    (
                        context.application_id,
                        context.tenant_id,
                        context.run_id,
                        field,
                        entity_id,
                    ),
                )
            ).fetchall()
        return tuple(ProvenanceLink.model_validate(row[0]) for row in rows)

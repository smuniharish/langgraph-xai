"""A PostgreSQL store for langgraph-xai, built on the `ProvenanceStore` base class.

langgraph-xai keeps records in memory by default. To persist them in a database,
subclass `ProvenanceStore` and implement five methods (`write`, `get`, `query`,
`parents`, and `children`); `lineage` and `close` are inherited. This module is a
complete, tested store for PostgreSQL that you can copy into your application:
one JSONB table, indexed for tenant and run isolation, written with idempotent
upserts.

Requires ``psycopg[binary,pool]`` (part of the ``examples`` dependency group) and
a database URL in ``XAI_POSTGRES_DSN``, for example
``postgresql://user:password@localhost:5432/xai``.

Run with:

    uv run --group examples python examples/postgres_store.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections import Counter
from importlib import import_module
from typing import TYPE_CHECKING, Any, ClassVar, TypedDict, cast

from langgraph.graph import END, START, StateGraph

from langgraph_xai import (
    EvidenceType,
    Execution,
    ProvenanceLink,
    ProvenanceStore,
    StoreFilter,
    XAIRuntime,
)
from langgraph_xai.core import XAIEvent

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from langgraph_xai import ExecutionContext
    from langgraph_xai.core import CanonicalEvent, StoreQuery

    type StoredItem = Execution | ProvenanceLink | CanonicalEvent

SCHEMA = """
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
    ON langgraph_xai_records (application_id, tenant_id, run_id, timestamp);
CREATE INDEX IF NOT EXISTS langgraph_xai_entity_idx
    ON langgraph_xai_records ((split_part(record_key, ':', 2)));
"""
_ORDER = "ORDER BY timestamp, COALESCE((payload->>'sequence')::int, -1), payload->>'id'"
_MODELS: dict[str, type[Execution | ProvenanceLink | XAIEvent]] = {
    model.__name__: model for model in (Execution, ProvenanceLink, *XAIEvent.__subclasses__())
}


def _record_id(item: StoredItem) -> str:
    return str(item.id)


def _decode(record_type: str, payload: Any) -> StoredItem:
    model = _MODELS.get(record_type)
    if model is None:
        raise ValueError(f"unsupported record type {record_type!r}")
    data = json.loads(payload) if isinstance(payload, str) else payload
    return cast("StoredItem", model.model_validate(data))


class PostgresProvenanceStore(ProvenanceStore):
    """A JSONB-backed store with indexed tenant and run isolation and idempotent upserts.

    Every record is one row keyed by ``"<record type>:<id>"``. Writes are upserts,
    so rewriting a record (for example an `Execution` when its run finishes)
    replaces it. Call `open` once before use.

    The store uses psycopg's asynchronous pool, which belongs to the event loop
    that opened it, so record through asynchronous graph calls (``ainvoke``,
    ``astream``, ``abatch``). On Windows, psycopg needs a selector event loop:
    ``asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)``.
    """

    SCHEMA: ClassVar[str] = SCHEMA
    """The DDL that `open` runs: the table and its indexes, all ``IF NOT EXISTS``."""

    def __init__(self, dsn: str, *, pool: Any | None = None) -> None:
        """Create a store for ``dsn``, or around an existing ``AsyncConnectionPool``.

        A pool passed in is owned by the caller and is not closed by `close`.
        """
        self._owns_pool = pool is None
        if pool is None:
            try:
                pool_class = import_module("psycopg_pool").AsyncConnectionPool
            except ImportError as exc:
                raise ImportError(
                    "PostgresProvenanceStore requires psycopg: pip install 'psycopg[binary,pool]'"
                ) from exc
            pool = pool_class(dsn, open=False)
        self._pool: Any = pool

    async def open(self, *, create_schema: bool = True) -> None:
        """Open the pool and, unless ``create_schema`` is false, create the schema.

        Creating the schema needs the ``CREATE`` privilege on the database schema,
        even when the table already exists. An application role limited to
        ``SELECT``, ``INSERT``, and ``UPDATE`` passes ``create_schema=False`` once
        `SCHEMA` has been applied by a privileged role, for example in a
        migration. If the schema cannot be created, a pool owned by the store is
        closed again, so no background reconnect workers are left running.
        """
        await self._pool.open()
        if not create_schema:
            return
        try:
            async with self._pool.connection() as connection:
                await connection.execute(SCHEMA)
        except BaseException:
            if self._owns_pool:
                await self._pool.close()
            raise

    async def write(self, item: StoredItem) -> None:
        """Insert or replace ``item``."""
        record_type = type(item).__name__
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
                    f"{record_type}:{_record_id(item)}",
                    record_type,
                    item.context.application_id,
                    item.context.tenant_id,
                    item.context.run_id,
                    item.timestamp,
                    item.model_dump_json(),
                ),
            )

    async def get(self, entity_id: str) -> StoredItem | None:
        """Return the record whose ``id`` is ``entity_id``, if any."""
        async with self._pool.connection() as connection:
            rows = await (
                await connection.execute(
                    "SELECT record_type, payload FROM langgraph_xai_records "
                    "WHERE split_part(record_key, ':', 2) = %s LIMIT 2",
                    (entity_id,),
                )
            ).fetchall()
        if len(rows) > 1:
            raise LookupError("entity ID is ambiguous; use an isolation-aware query")
        return _decode(*rows[0]) if rows else None

    async def query(self, query: StoreQuery) -> AsyncIterator[StoredItem]:
        """Yield the records matching a `StoreFilter`."""
        if not isinstance(query, StoreFilter):
            raise TypeError("PostgresProvenanceStore requires StoreFilter")
        record_type = query.item_type.__name__ if query.item_type else None
        async with self._pool.connection() as connection:
            rows = await (
                await connection.execute(
                    f"""
                    SELECT record_type, payload FROM langgraph_xai_records
                    WHERE application_id = %s AND tenant_id = %s
                      AND (%s::uuid IS NULL OR run_id = %s::uuid)
                      AND (%s::text IS NULL OR record_type = %s::text)
                    {_ORDER} LIMIT %s OFFSET %s
                    """,  # noqa: S608 - only the constant ORDER BY clause is interpolated
                    (
                        query.application_id,
                        query.tenant_id,
                        query.run_id,
                        query.run_id,
                        record_type,
                        record_type,
                        query.limit,
                        query.offset,
                    ),
                )
            ).fetchall()
        for row in rows:
            yield _decode(*row)

    async def parents(
        self, entity_id: str, *, context: ExecutionContext
    ) -> Sequence[ProvenanceLink]:
        """Return the links whose target is ``entity_id`` within the context's run."""
        return await self._links(entity_id, context, "target_id")

    async def children(
        self, entity_id: str, *, context: ExecutionContext
    ) -> Sequence[ProvenanceLink]:
        """Return the links whose source is ``entity_id`` within the context's run."""
        return await self._links(entity_id, context, "source_id")

    async def close(self) -> None:
        """Close the connection pool if this store created it."""
        if self._owns_pool:
            await self._pool.close()

    async def _links(
        self, entity_id: str, context: ExecutionContext, field: str
    ) -> tuple[ProvenanceLink, ...]:
        async with self._pool.connection() as connection:
            rows = await (
                await connection.execute(
                    f"""
                    SELECT payload FROM langgraph_xai_records
                    WHERE record_type = 'ProvenanceLink'
                      AND application_id = %s AND tenant_id = %s AND run_id = %s
                      AND payload->>%s = %s
                    {_ORDER}
                    """,  # noqa: S608 - only the constant ORDER BY clause is interpolated
                    (context.application_id, context.tenant_id, context.run_id, field, entity_id),
                )
            ).fetchall()
        return tuple(
            ProvenanceLink.model_validate(json.loads(row[0]) if isinstance(row[0], str) else row[0])
            for row in rows
        )


class Review(TypedDict, total=False):
    transaction_id: str
    risk_score: float


async def main() -> None:
    dsn = os.getenv("XAI_POSTGRES_DSN")
    if not dsn:
        raise SystemExit(
            "Set XAI_POSTGRES_DSN to a PostgreSQL URL, "
            "for example postgresql://user:password@localhost:5432/xai"
        )
    store = PostgresProvenanceStore(dsn)
    await store.open()
    xai = XAIRuntime(application_id="payments", tenant_id="acme-bank", graph_id="fraud-review")
    xai.register(ProvenanceStore, store)

    async def score_risk(state: Review) -> Review:
        evidence = await xai.record_evidence(
            EvidenceType.TOOL_RESULT, summary="Fraud model scored the transaction 0.91."
        )
        await xai.record_provenance(
            f"transactions://{state['transaction_id']}", evidence.id, "DERIVED_FROM"
        )
        return {"risk_score": 0.91}

    builder = StateGraph(Review)
    builder.add_node("score_risk", score_risk)
    builder.add_edge(START, "score_risk")
    builder.add_edge("score_risk", END)
    graph = xai.instrument(builder.compile())

    try:
        with xai.collect_runs() as runs:
            await graph.ainvoke({"transaction_id": "txn-8841"})
        (run,) = runs
        records = [
            record
            async for record in store.query(
                StoreFilter(application_id="payments", tenant_id="acme-bank", run_id=run.run_id)
            )
        ]
        print(f"Stored {len(records)} records for run {run.run_id}:")
        for name, count in sorted(Counter(type(record).__name__ for record in records).items()):
            print(f"  {name}: {count}")
        lineage = await store.lineage(str(run.evidence[0].id), context=run.execution.context)
        print(
            "Lineage of the fraud score:",
            [f"{link.target_id} {link.relation} {link.source_id}" for link in lineage],
        )
    finally:
        await xai.close()


if __name__ == "__main__":
    # psycopg's asynchronous mode needs a selector event loop on Windows.
    asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop if sys.platform == "win32" else None)

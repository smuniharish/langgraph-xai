"""Live integration test for PostgresProvenanceStore against a real PostgreSQL instance.

Requires ``XAI_TEST_POSTGRES_DSN`` to point at a reachable PostgreSQL database, for example
one started with Podman:

    podman run -d --name xai-postgres -e POSTGRES_PASSWORD=xai_test -e POSTGRES_DB=xai \\
        -p 55432:5432 postgres:16-alpine

    $env:XAI_TEST_POSTGRES_DSN = "postgresql://postgres:xai_test@<host>:55432/xai"
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

from langgraph_xai.core import ExecutionContext, ProvenanceLink
from langgraph_xai.storage import PostgresProvenanceStore, StoreFilter

pytestmark = pytest.mark.postgres

if sys.platform == "win32":
    # psycopg's async connection pool requires a selector-based event loop; the default
    # ProactorEventLoop on Windows cannot host it.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def _context(tenant: str = "tenant") -> ExecutionContext:
    return ExecutionContext(application_id="live-app", tenant_id=tenant, graph_id="graph")


async def _fresh_store(dsn: str) -> PostgresProvenanceStore:
    """Open a store against a truncated table so repeated live runs stay deterministic."""
    store = PostgresProvenanceStore(dsn)
    await store.open()
    async with store._pool.connection() as connection:
        await connection.execute("TRUNCATE TABLE langgraph_xai_records")
    return store


@pytest.mark.asyncio
async def test_postgres_store_persists_and_serves_lineage_queries() -> None:
    dsn = os.getenv("XAI_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("XAI_TEST_POSTGRES_DSN is not configured")
    pytest.importorskip("psycopg_pool")

    store = await _fresh_store(dsn)
    try:
        scope = _context()
        links = [
            ProvenanceLink(
                source_id="bank-api", target_id="transaction", relation="PRODUCED_BY", context=scope
            ),
            ProvenanceLink(
                source_id="transaction",
                target_id="fraud-score",
                relation="DERIVED_FROM",
                context=scope,
            ),
            ProvenanceLink(
                source_id="fraud-score", target_id="decision", relation="INFLUENCED", context=scope
            ),
        ]
        for link in links:
            await store.write(link)
            # Re-write to prove idempotency via ON CONFLICT DO UPDATE.
            await store.write(link)

        fetched = await store.get(str(links[0].id))
        assert fetched is not None
        assert fetched.id == links[0].id

        records = [
            item
            async for item in store.query(
                StoreFilter(application_id="live-app", tenant_id="tenant", limit=50)
            )
        ]
        assert len(records) == 3

        lineage = await store.lineage("decision", context=scope)
        lineage_sources = {str(link.source_id) for link in lineage}
        assert lineage_sources == {"bank-api", "transaction", "fraud-score"}

        parents_of_decision = await store.parents("decision", context=scope)
        assert [str(link.source_id) for link in parents_of_decision] == ["fraud-score"]

        children_of_transaction = await store.children("transaction", context=scope)
        assert [str(link.target_id) for link in children_of_transaction] == ["fraud-score"]
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_postgres_store_isolates_tenants() -> None:
    dsn = os.getenv("XAI_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("XAI_TEST_POSTGRES_DSN is not configured")
    pytest.importorskip("psycopg_pool")

    store = await _fresh_store(dsn)
    try:
        first = ProvenanceLink(
            source_id="x", target_id="y", relation="A", context=_context("alpha")
        )
        second = ProvenanceLink(
            source_id="x", target_id="y", relation="B", context=_context("beta")
        )
        await store.write(first)
        await store.write(second)

        alpha_only = [
            item
            async for item in store.query(StoreFilter(application_id="live-app", tenant_id="alpha"))
        ]
        assert {item.id for item in alpha_only} == {first.id}
    finally:
        await store.close()

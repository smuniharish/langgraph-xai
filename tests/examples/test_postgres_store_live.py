"""Live tests for the example PostgreSQL store against a real PostgreSQL server.

Set ``XAI_TEST_POSTGRES_DSN`` to a disposable database, for example::

    podman run -d --name xai-postgres -e POSTGRES_PASSWORD=xai -e POSTGRES_DB=xai \\
        -p 55432:5432 postgres:16-alpine
    export XAI_TEST_POSTGRES_DSN="postgresql://postgres:xai@localhost:55432/xai"

psycopg's async pool needs a selector event loop on Windows, so each test runs
its coroutine on an explicitly chosen loop instead of changing the global policy.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import TYPE_CHECKING

import pytest

from examples import postgres_store
from examples.postgres_store import PostgresProvenanceStore
from langgraph_xai import Execution, ExecutionStatus, ProvenanceLink, ProvenanceStore, XAIRuntime
from langgraph_xai.core import NodeExecutionEvent, StateTransitionEvent
from langgraph_xai.storage import StoreFilter
from tests.helpers import context, linear_graph

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine
    from typing import Any

pytestmark = pytest.mark.postgres
DSN = os.getenv("XAI_TEST_POSTGRES_DSN")
requires_postgres = pytest.mark.skipif(not DSN, reason="XAI_TEST_POSTGRES_DSN is not configured")


def run(test: Callable[[str], Coroutine[Any, Any, None]]) -> None:
    pytest.importorskip("psycopg_pool")
    assert DSN is not None
    factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    asyncio.run(test(DSN), loop_factory=factory)


async def fresh_store(dsn: str) -> PostgresProvenanceStore:
    store = PostgresProvenanceStore(dsn)
    await store.open()
    async with store._pool.connection() as connection:
        await connection.execute("TRUNCATE TABLE langgraph_xai_records")
    return store


@requires_postgres
def test_links_are_persisted_idempotently_and_walkable() -> None:
    async def scenario(dsn: str) -> None:
        store = await fresh_store(dsn)
        try:
            scope = context()
            links = [
                ProvenanceLink(
                    source_id="bank-api",
                    target_id="transaction",
                    relation="PRODUCED_BY",
                    context=scope,
                ),
                ProvenanceLink(
                    source_id="transaction",
                    target_id="score",
                    relation="DERIVED_FROM",
                    context=scope,
                ),
                ProvenanceLink(
                    source_id="score", target_id="decision", relation="SUPPORTED_BY", context=scope
                ),
            ]
            for item in links:
                await store.write(item)
                await store.write(item)

            assert await store.get(str(links[0].id)) == links[0]
            records = [
                item
                async for item in store.query(StoreFilter(application_id="app", tenant_id="tenant"))
            ]
            assert len(records) == 3
            lineage = await store.lineage("decision", context=scope)
            assert [str(item.source_id) for item in lineage] == ["score", "transaction", "bank-api"]
            assert [
                str(item.source_id) for item in await store.parents("decision", context=scope)
            ] == ["score"]
            assert [
                str(item.target_id) for item in await store.children("transaction", context=scope)
            ] == ["score"]
        finally:
            await store.close()

    run(scenario)


@requires_postgres
def test_tenants_are_isolated() -> None:
    async def scenario(dsn: str) -> None:
        store = await fresh_store(dsn)
        try:
            alpha = ProvenanceLink(
                source_id="x", target_id="y", relation="A", context=context("alpha")
            )
            beta = ProvenanceLink(
                source_id="x", target_id="y", relation="B", context=context("beta")
            )
            await store.write(alpha)
            await store.write(beta)

            only_alpha = [
                item
                async for item in store.query(StoreFilter(application_id="app", tenant_id="alpha"))
            ]
            assert [item.id for item in only_alpha] == [alpha.id]
        finally:
            await store.close()

    run(scenario)


@requires_postgres
def test_instrumented_graph_runs_are_persisted_end_to_end() -> None:
    async def scenario(dsn: str) -> None:
        store = await fresh_store(dsn)
        runtime = XAIRuntime(application_id="app", tenant_id="tenant", graph_id="live")
        runtime.register(ProvenanceStore, store)
        graph = runtime.instrument(
            linear_graph(
                ("score", lambda state: {"count": 1}), ("answer", lambda state: {"answer": "ok"})
            )
        )
        try:
            with runtime.collect_runs() as runs:
                await graph.ainvoke({"question": "q"})
            (run_,) = runs
            records = [
                item
                async for item in store.query(
                    StoreFilter(
                        application_id="app", tenant_id="tenant", run_id=run_.run_id, limit=50
                    )
                )
            ]
            executions = [item for item in records if isinstance(item, Execution)]
            assert [item.status for item in executions] == [ExecutionStatus.COMPLETED]
            assert len(executions[0].nodes) == 2
            assert sum(isinstance(item, NodeExecutionEvent) for item in records) == 2
            assert sum(isinstance(item, StateTransitionEvent) for item in records) == 2
            sequences = [item.sequence for item in records if hasattr(item, "sequence")]
            assert sequences == sorted(sequences)
            assert runtime.errors == ()
        finally:
            await runtime.close()

    run(scenario)


@requires_postgres
def test_the_example_demo_persists_a_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert DSN is not None
    monkeypatch.setenv("XAI_POSTGRES_DSN", DSN)

    run(lambda dsn: postgres_store.main())

    output = capsys.readouterr().out
    assert "Stored 6 records for run" in output
    assert "ProvenanceLink: 1" in output
    assert "DERIVED_FROM transactions://txn-8841" in output

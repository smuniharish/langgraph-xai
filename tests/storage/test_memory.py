import asyncio

import pytest

from langgraph_xai.core import ExecutionContext, ProvenanceLink
from langgraph_xai.storage import InMemoryProvenanceStore, StoreFilter


def context(tenant: str = "tenant") -> ExecutionContext:
    return ExecutionContext(application_id="app", tenant_id=tenant, graph_id="graph")


@pytest.mark.asyncio
async def test_lineage_is_scoped_cycle_safe_and_idempotent() -> None:
    store = InMemoryProvenanceStore()
    scope = context()
    links = [
        ProvenanceLink(source_id="a", target_id="b", relation="DERIVED_FROM", context=scope),
        ProvenanceLink(source_id="b", target_id="c", relation="DERIVED_FROM", context=scope),
        ProvenanceLink(source_id="c", target_id="a", relation="DERIVED_FROM", context=scope),
    ]
    for link in links:
        await store.write(link)
        await store.write(link)

    lineage = await store.lineage("c", context=scope)

    assert {link.id for link in lineage} == {link.id for link in links}


@pytest.mark.asyncio
async def test_query_enforces_application_tenant_and_run_isolation() -> None:
    store = InMemoryProvenanceStore()
    first = ProvenanceLink(source_id="a", target_id="b", relation="A", context=context("one"))
    second = ProvenanceLink(source_id="a", target_id="b", relation="B", context=context("two"))
    await store.write(first)
    await store.write(second)

    records = [
        item async for item in store.query(StoreFilter(application_id="app", tenant_id="one"))
    ]

    assert [item.id for item in records] == [first.id]


@pytest.mark.asyncio
async def test_concurrent_writes_do_not_lose_records() -> None:
    store = InMemoryProvenanceStore()
    scope = context()
    links = [
        ProvenanceLink(
            source_id=f"source-{index}",
            target_id="decision",
            relation="INFLUENCED",
            context=scope,
        )
        for index in range(150)
    ]

    await asyncio.gather(*(store.write(link) for link in links))
    records = [
        item
        async for item in store.query(
            StoreFilter(application_id="app", tenant_id="tenant", limit=200)
        )
    ]

    assert len(records) == 150

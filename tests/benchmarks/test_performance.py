"""Generous performance budgets that catch order-of-magnitude regressions."""

import asyncio
import time

import pytest

from langgraph_xai import ProvenanceLink, XAIRuntime
from langgraph_xai.storage import InMemoryProvenanceStore
from tests.helpers import State, context, linear_graph

pytestmark = pytest.mark.benchmark


async def test_1000_concurrent_store_writes_stay_within_budget() -> None:
    store = InMemoryProvenanceStore()
    ctx = context()
    links = [
        ProvenanceLink(context=ctx, source_id=f"source-{i}", target_id="decision", relation="r")
        for i in range(1000)
    ]

    started = time.perf_counter()
    await asyncio.gather(*(store.write(link) for link in links))
    lineage = await store.lineage("decision", context=ctx)

    assert len(lineage) == 1000
    assert time.perf_counter() - started < 2.0


def _graph():
    def step(key: str):
        return lambda state: {key: state.get(key, "") + "."}

    return linear_graph(*((f"n{i}", step("note")) for i in range(5)), state=State)


async def test_instrumented_async_runs_stay_within_budget() -> None:
    xai = XAIRuntime()
    graph = xai.instrument(_graph())

    started = time.perf_counter()
    for _ in range(100):
        await graph.ainvoke({"question": "q"})

    assert time.perf_counter() - started < 10.0
    assert xai.errors == ()


def test_instrumented_sync_runs_reuse_the_thread_loop_within_budget() -> None:
    xai = XAIRuntime()
    graph = xai.instrument(_graph())

    started = time.perf_counter()
    for _ in range(100):
        graph.invoke({"question": "q"})

    assert time.perf_counter() - started < 10.0
    assert xai.errors == ()

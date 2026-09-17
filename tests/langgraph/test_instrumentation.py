import asyncio
from typing import TypedDict

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel

from langgraph_xai import Execution, ExecutionStatus, HumanInteractionType, XAIRuntime
from langgraph_xai.core import ProvenanceStore
from langgraph_xai.storage import InMemoryProvenanceStore, StoreFilter


class State(BaseModel):
    value: int


def graph():
    builder = StateGraph(State)
    builder.add_node("increment", lambda state: {"value": state.value + 1})
    builder.add_edge(START, "increment")
    builder.add_edge("increment", END)
    return builder.compile()


@pytest.mark.asyncio
async def test_instrumented_graph_preserves_ainvoke_output_and_captures_execution() -> None:
    runtime = XAIRuntime(application_id="app", tenant_id="tenant", graph_id="counter")

    result = await runtime.instrument(graph()).ainvoke({"value": 1})

    assert result == {"value": 2}
    store = runtime.registry.require(ProvenanceStore)
    assert isinstance(store, InMemoryProvenanceStore)
    records = [
        item async for item in store.query(StoreFilter(application_id="app", tenant_id="tenant"))
    ]
    assert records


@pytest.mark.asyncio
async def test_100_concurrent_runs_keep_tenants_isolated() -> None:
    runtime = XAIRuntime(application_id="app", graph_id="counter")
    instrumented = runtime.instrument(graph())

    results = await asyncio.gather(
        *(
            instrumented.ainvoke(
                {"value": index},
                config={"metadata": {"xai_tenant_id": f"tenant-{index % 5}"}},
            )
            for index in range(120)
        )
    )

    assert [result["value"] for result in results] == [index + 1 for index in range(120)]
    store = runtime.registry.require(ProvenanceStore)
    assert isinstance(store, InMemoryProvenanceStore)
    for tenant in range(5):
        records = [
            item
            async for item in store.query(
                StoreFilter(application_id="app", tenant_id=f"tenant-{tenant}", limit=200)
            )
        ]
        assert records
        assert all(item.context.tenant_id == f"tenant-{tenant}" for item in records)


class HitlState(TypedDict, total=False):
    amount: float
    approved: bool


def _hitl_graph():
    def human_review(state: HitlState) -> HitlState:
        decision = interrupt({"question": "approve?", "amount": state["amount"]})
        return {"approved": bool(decision)}

    # Pyrefly does not yet recognize a plain TypedDict as satisfying
    # LangGraph's structural StateLike protocol bound; this is a real,
    # supported LangGraph state schema at runtime (see langgraph.typing.StateT).
    builder = StateGraph(HitlState)  # pyrefly: ignore[bad-specialization]
    builder.add_node("human_review", human_review)
    builder.add_edge(START, "human_review")
    builder.add_edge("human_review", END)
    return builder.compile(checkpointer=InMemorySaver())


@pytest.mark.asyncio
async def test_interrupt_is_captured_as_interrupted_not_completed() -> None:
    """Regression test: LangGraph reports a pause via a ``__interrupt__`` key in
    its output rather than through the LangChain callback system, so an
    interrupted run must not be silently recorded as COMPLETED."""
    runtime = XAIRuntime(application_id="app", tenant_id="tenant", graph_id="hitl")
    instrumented = runtime.instrument(_hitl_graph())
    thread = {"configurable": {"thread_id": "wire-1"}}

    paused = await instrumented.ainvoke({"amount": 100.0}, thread)
    assert "__interrupt__" in paused

    resumed = await instrumented.ainvoke(Command(resume=True), thread)
    assert resumed == {"amount": 100.0, "approved": True}

    store = runtime.registry.require(ProvenanceStore)
    assert isinstance(store, InMemoryProvenanceStore)
    executions = [
        item
        async for item in store.query(
            StoreFilter(application_id="app", tenant_id="tenant", item_type=Execution, limit=50)
        )
        if isinstance(item, Execution)
    ]

    assert any(execution.status == ExecutionStatus.INTERRUPTED for execution in executions)
    assert any(execution.status == ExecutionStatus.COMPLETED for execution in executions)
    interrupted = next(
        execution for execution in executions if execution.status == ExecutionStatus.INTERRUPTED
    )
    assert any(
        interaction.interaction_type == HumanInteractionType.INTERRUPT
        for interaction in interrupted.human_interactions
    )
    completed = next(
        execution for execution in executions if execution.status == ExecutionStatus.COMPLETED
    )
    assert any(
        interaction.interaction_type == HumanInteractionType.RESUME
        for interaction in completed.human_interactions
    )

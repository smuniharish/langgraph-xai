"""Exercise every InstrumentedGraph execution method: invoke, stream, batch,
their async counterparts, and the error/cancellation paths of each.

``tests/langgraph/test_instrumentation.py`` only ever exercises ``ainvoke``.
This file closes that gap: every method ``InstrumentedGraph`` proxies must
preserve the wrapped graph's output/behavior exactly, and must record a
correctly-statused ``Execution`` (``COMPLETED``, ``FAILED``, or
``CANCELLED``) no matter which entry point was used.
"""

import asyncio

import pytest
from langgraph.graph import END, START, StateGraph

from langgraph_xai import Execution, ExecutionStatus, XAIRuntime
from langgraph_xai.core import ProvenanceStore
from langgraph_xai.storage import InMemoryProvenanceStore, StoreFilter


def _increment_graph():
    builder = StateGraph(dict)  # pyrefly: ignore[bad-specialization]
    builder.add_node("increment", lambda state: {"x": state["x"] + 1})
    builder.add_edge(START, "increment")
    builder.add_edge("increment", END)
    return builder.compile()


def _failing_graph():
    def boom(state: dict) -> dict:
        if state["x"] == 1:
            raise ValueError("node failed")
        return {"x": state["x"] + 1}

    builder = StateGraph(dict)  # pyrefly: ignore[bad-specialization]
    builder.add_node("boom", boom)
    builder.add_edge(START, "boom")
    builder.add_edge("boom", END)
    return builder.compile()


def _slow_graph():
    async def slow_node(state: dict) -> dict:
        await asyncio.sleep(10)
        return {"x": state["x"] + 1}

    builder = StateGraph(dict)  # pyrefly: ignore[bad-specialization]
    builder.add_node("slow", slow_node)
    builder.add_edge(START, "slow")
    builder.add_edge("slow", END)
    return builder.compile()


async def _executions(runtime: XAIRuntime) -> list[Execution]:
    store = runtime.registry.require(ProvenanceStore)
    assert isinstance(store, InMemoryProvenanceStore)
    return [
        item
        async for item in store.query(
            StoreFilter(
                application_id=runtime.application_id,
                tenant_id=runtime.tenant_id,
                item_type=Execution,
            )
        )
        if isinstance(item, Execution)
    ]


# --- invoke (sync) ----------------------------------------------------------


def test_sync_invoke_preserves_output_and_captures_completed_execution() -> None:
    runtime = XAIRuntime(application_id="app", tenant_id="tenant", graph_id="counter")
    instrumented = runtime.instrument(_increment_graph())

    result = instrumented.invoke({"x": 1})

    assert result == {"x": 2}
    executions = runtime.run_sync(_executions(runtime))
    assert len(executions) == 1
    assert executions[0].status == ExecutionStatus.COMPLETED


def test_sync_invoke_captures_failed_execution_and_reraises() -> None:
    runtime = XAIRuntime(application_id="app", tenant_id="tenant", graph_id="counter")
    instrumented = runtime.instrument(_failing_graph())

    with pytest.raises(ValueError, match="node failed"):
        instrumented.invoke({"x": 1})

    executions = runtime.run_sync(_executions(runtime))
    assert len(executions) == 1
    assert executions[0].status == ExecutionStatus.FAILED
    assert executions[0].exceptions
    assert executions[0].exceptions[0].exception_type == "ValueError"


# --- stream (sync) -----------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_stream_yields_chunks_and_captures_completed_execution() -> None:
    runtime = XAIRuntime(application_id="app", tenant_id="tenant", graph_id="counter")
    instrumented = runtime.instrument(_increment_graph())

    chunks = list(instrumented.stream({"x": 1}))

    assert chunks == [{"increment": {"x": 2}}]
    executions = await _executions(runtime)
    assert len(executions) == 1
    assert executions[0].status == ExecutionStatus.COMPLETED


@pytest.mark.asyncio
async def test_sync_stream_captures_failed_execution_and_reraises() -> None:
    runtime = XAIRuntime(application_id="app", tenant_id="tenant", graph_id="counter")
    instrumented = runtime.instrument(_failing_graph())

    with pytest.raises(ValueError, match="node failed"):
        list(instrumented.stream({"x": 1}))

    executions = await _executions(runtime)
    assert len(executions) == 1
    assert executions[0].status == ExecutionStatus.FAILED
    assert executions[0].exceptions
    assert executions[0].exceptions[0].exception_type == "ValueError"


@pytest.mark.asyncio
async def test_sync_stream_closed_early_captures_cancelled_execution() -> None:
    """Breaking out of a ``for`` loop over ``.stream(...)`` without fully
    draining it triggers ``GeneratorExit`` when the generator is closed --
    this must be captured as CANCELLED, not silently dropped."""
    runtime = XAIRuntime(application_id="app", tenant_id="tenant", graph_id="counter")

    def multi_step_graph():
        builder = StateGraph(dict)  # pyrefly: ignore[bad-specialization]
        builder.add_node("a", lambda state: {"x": state["x"] + 1})
        builder.add_node("b", lambda state: {"x": state["x"] + 1})
        builder.add_edge(START, "a")
        builder.add_edge("a", "b")
        builder.add_edge("b", END)
        return builder.compile()

    instrumented = runtime.instrument(multi_step_graph())
    generator = instrumented.stream({"x": 1})
    next(generator)  # consume exactly one chunk, then abandon the generator
    generator.close()

    executions = await _executions(runtime)
    assert len(executions) == 1
    assert executions[0].status == ExecutionStatus.CANCELLED


# --- astream -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_astream_yields_chunks_and_captures_completed_execution() -> None:
    runtime = XAIRuntime(application_id="app", tenant_id="tenant", graph_id="counter")
    instrumented = runtime.instrument(_increment_graph())

    chunks = [chunk async for chunk in instrumented.astream({"x": 1})]

    assert chunks == [{"increment": {"x": 2}}]
    executions = await _executions(runtime)
    assert len(executions) == 1
    assert executions[0].status == ExecutionStatus.COMPLETED


@pytest.mark.asyncio
async def test_astream_captures_failed_execution_and_reraises() -> None:
    runtime = XAIRuntime(application_id="app", tenant_id="tenant", graph_id="counter")
    instrumented = runtime.instrument(_failing_graph())

    with pytest.raises(ValueError, match="node failed"):
        [chunk async for chunk in instrumented.astream({"x": 1})]

    executions = await _executions(runtime)
    assert len(executions) == 1
    assert executions[0].status == ExecutionStatus.FAILED


@pytest.mark.asyncio
async def test_astream_cancelled_task_captures_cancelled_execution() -> None:
    runtime = XAIRuntime(application_id="app", tenant_id="tenant", graph_id="counter")
    instrumented = runtime.instrument(_slow_graph())

    async def drain() -> None:
        async for _ in instrumented.astream({"x": 1}):
            pass

    task = asyncio.ensure_future(drain())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    executions = await _executions(runtime)
    assert len(executions) == 1
    assert executions[0].status == ExecutionStatus.CANCELLED


# --- batch (sync) --------------------------------------------------------------


def test_sync_batch_captures_one_execution_per_input() -> None:
    runtime = XAIRuntime(application_id="app", tenant_id="tenant", graph_id="counter")
    instrumented = runtime.instrument(_increment_graph())

    results = instrumented.batch([{"x": 1}, {"x": 2}, {"x": 3}])

    assert results == [{"x": 2}, {"x": 3}, {"x": 4}]
    executions = runtime.run_sync(_executions(runtime))
    assert len(executions) == 3
    assert all(execution.status == ExecutionStatus.COMPLETED for execution in executions)
    # Every input got its own run_id -- batch does not collapse them together.
    assert len({execution.context.run_id for execution in executions}) == 3


def test_sync_batch_raises_and_fails_every_run_when_whole_call_errors() -> None:
    """With the default ``return_exceptions=False``, one failing input fails
    the entire ``.batch()`` call -- every run started for that batch must be
    recorded FAILED, not left dangling as RUNNING."""
    runtime = XAIRuntime(application_id="app", tenant_id="tenant", graph_id="counter")
    instrumented = runtime.instrument(_failing_graph())

    with pytest.raises(ValueError, match="node failed"):
        instrumented.batch([{"x": 1}, {"x": 5}])

    executions = runtime.run_sync(_executions(runtime))
    assert len(executions) == 2
    assert all(execution.status == ExecutionStatus.FAILED for execution in executions)


def test_sync_batch_return_exceptions_marks_only_the_failed_input() -> None:
    """With ``return_exceptions=True`` the overall call succeeds, but one
    output is itself an exception object -- only that input's run should be
    FAILED; the others must still be COMPLETED."""
    runtime = XAIRuntime(application_id="app", tenant_id="tenant", graph_id="counter")
    instrumented = runtime.instrument(_failing_graph())

    results = instrumented.batch([{"x": 1}, {"x": 5}], return_exceptions=True)

    assert isinstance(results[0], ValueError)
    assert results[1] == {"x": 6}

    executions = runtime.run_sync(_executions(runtime))
    assert len(executions) == 2
    statuses = sorted(execution.status for execution in executions)
    assert statuses == sorted([ExecutionStatus.FAILED, ExecutionStatus.COMPLETED])


# --- abatch --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_abatch_captures_one_execution_per_input() -> None:
    runtime = XAIRuntime(application_id="app", tenant_id="tenant", graph_id="counter")
    instrumented = runtime.instrument(_increment_graph())

    results = await instrumented.abatch([{"x": 1}, {"x": 2}])

    assert results == [{"x": 2}, {"x": 3}]
    executions = await _executions(runtime)
    assert len(executions) == 2
    assert all(execution.status == ExecutionStatus.COMPLETED for execution in executions)


@pytest.mark.asyncio
async def test_abatch_return_exceptions_marks_only_the_failed_input() -> None:
    runtime = XAIRuntime(application_id="app", tenant_id="tenant", graph_id="counter")
    instrumented = runtime.instrument(_failing_graph())

    results = await instrumented.abatch([{"x": 1}, {"x": 5}], return_exceptions=True)

    assert isinstance(results[0], ValueError)
    assert results[1] == {"x": 6}

    executions = await _executions(runtime)
    assert len(executions) == 2
    statuses = sorted(execution.status for execution in executions)
    assert statuses == sorted([ExecutionStatus.FAILED, ExecutionStatus.COMPLETED])


@pytest.mark.asyncio
async def test_abatch_raises_and_fails_every_run_when_whole_call_errors() -> None:
    runtime = XAIRuntime(application_id="app", tenant_id="tenant", graph_id="counter")
    instrumented = runtime.instrument(_failing_graph())

    with pytest.raises(ValueError, match="node failed"):
        await instrumented.abatch([{"x": 1}, {"x": 5}])

    executions = await _executions(runtime)
    assert len(executions) == 2
    assert all(execution.status == ExecutionStatus.FAILED for execution in executions)


@pytest.mark.asyncio
async def test_abatch_cancelled_task_fails_every_run_as_cancelled() -> None:
    runtime = XAIRuntime(application_id="app", tenant_id="tenant", graph_id="counter")
    instrumented = runtime.instrument(_slow_graph())

    task = asyncio.ensure_future(instrumented.abatch([{"x": 1}, {"x": 2}]))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    executions = await _executions(runtime)
    assert len(executions) == 2
    assert all(execution.status == ExecutionStatus.CANCELLED for execution in executions)


# --- reentrancy and with_config -------------------------------------------------


@pytest.mark.asyncio
async def test_nested_ainvoke_from_within_an_active_run_is_not_double_wrapped() -> None:
    """Calling an *already-instrumented* graph's own method again while a run
    started by the same runtime is active must delegate straight through to
    the wrapped graph (no second, nested Execution) -- current_run always
    means the outermost run.
    """
    runtime = XAIRuntime(application_id="app", tenant_id="tenant", graph_id="outer")
    inner = runtime.instrument(_increment_graph())

    async def outer_node(state: dict) -> dict:
        # Invoked from inside an already-active run for this same runtime.
        return await inner.ainvoke(state)

    builder = StateGraph(dict)  # pyrefly: ignore[bad-specialization]
    builder.add_node("outer", outer_node)
    builder.add_edge(START, "outer")
    builder.add_edge("outer", END)
    outer = runtime.instrument(builder.compile())

    result = await outer.ainvoke({"x": 1})

    assert result == {"x": 2}
    # Exactly one Execution: the outer run. The inner ainvoke() call detected
    # runtime.is_instrumenting() and delegated straight to the wrapped graph.
    executions = await _executions(runtime)
    assert len(executions) == 1


def test_with_config_preserves_instrumentation_and_wrapped_graph_config() -> None:
    runtime = XAIRuntime(application_id="app", tenant_id="tenant", graph_id="counter")
    instrumented = runtime.instrument(_increment_graph())

    configured = instrumented.with_config({"run_name": "custom"})

    assert configured is not instrumented
    assert configured.runtime is runtime
    result = configured.invoke({"x": 1})
    assert result == {"x": 2}

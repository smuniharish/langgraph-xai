"""Verify cross-node correlation and transient-failure capture in one real run.

This composes two locally defined "agents" (a researcher and a writer) into a
single supervisor graph, where the researcher's tool fails once and recovers
through LangChain's built-in retry. It then queries the provenance store to
prove, with real captured records rather than assumption, that:

1. every artifact from both agents and every retry attempt shares one
   ``run_id``/``trace_id`` (correlation holds across subgraphs and retries), and
2. **both** the failed first attempt and the succeeded retry are captured as
   distinct ``ToolExecution`` records (``status="failed"`` then
   ``status="succeeded"``), each with its own ``tool_call_id`` but the same
   ``run_id`` -- so the failure is never silently lost even though the
   overall execution still completes successfully.

Run with:

    uv run python examples/multi_agent_retry_correlation.py
"""

import asyncio
import json

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from langgraph_xai import Execution, XAIRuntime
from langgraph_xai.core import ToolExecutionEvent, XAIEvent
from langgraph_xai.core.protocols import ProvenanceStore
from langgraph_xai.storage.memory import StoreFilter

_attempts = 0


@tool
def flaky_market_data_lookup(symbol: str) -> str:
    """Look up market data for a symbol; fails transiently on the first call."""
    global _attempts
    _attempts += 1
    if _attempts == 1:
        raise TimeoutError("simulated transient upstream timeout")
    return f"{symbol}: last=142.10, change=+1.4%"


retrying_tool = flaky_market_data_lookup.with_retry(stop_after_attempt=3)


class SupervisorState(TypedDict, total=False):
    symbol: str
    research: str
    report: str


def researcher(state: SupervisorState, config: RunnableConfig) -> SupervisorState:
    finding = retrying_tool.invoke({"symbol": state["symbol"]}, config=config)
    return {"research": finding}


def writer(state: SupervisorState) -> SupervisorState:
    return {"report": f"Daily brief for {state['symbol']}: {state['research']}"}


async def main() -> None:
    builder = StateGraph(SupervisorState)
    builder.add_node("researcher", researcher)
    builder.add_node("writer", writer)
    builder.add_edge(START, "researcher")
    builder.add_edge("researcher", "writer")
    builder.add_edge("writer", END)
    graph = builder.compile()

    runtime = XAIRuntime(
        application_id="docs-verification",
        tenant_id="xgraph-dev",
        graph_id="supervisor-researcher-writer",
    )
    result = await runtime.instrument(graph).ainvoke(
        {"symbol": "ACME"},
        config={"metadata": {"trace_id": "multi-agent-retry-demo-0001"}},
    )
    print("--- Final state ---")
    print(json.dumps(result, indent=2))

    store = runtime.registry.get(ProvenanceStore)
    context = runtime.context_from_config({"metadata": {"trace_id": "multi-agent-retry-demo-0001"}})
    records = [
        record
        async for record in store.query(
            StoreFilter(
                application_id=context.application_id, tenant_id=context.tenant_id, limit=200
            )
        )
    ]

    run_ids = {str(record.context.run_id) for record in records}
    trace_ids = {record.context.trace_id for record in records}
    print(
        f"\n--- {len(records)} records captured; "
        f"distinct run_ids={run_ids}; trace_ids={trace_ids} ---"
    )
    for record in records:
        kind = record.event_type if isinstance(record, XAIEvent) else type(record).__name__
        print(" -", kind)
    assert len(run_ids) == 1, "every artifact from both agents must share one run_id"
    assert trace_ids == {"multi-agent-retry-demo-0001"}, "trace_id must propagate to every artifact"

    tool_executions = [record.tool for record in records if isinstance(record, ToolExecutionEvent)]
    statuses = [tool_exec.status for tool_exec in tool_executions]
    call_ids = {tool_exec.tool_call_id for tool_exec in tool_executions}
    print("\n--- Tool attempts captured for the flaky tool ---")
    for tool_exec in tool_executions:
        error = tool_exec.metadata.get("error_type")
        print(f" - status={tool_exec.status!r} tool_call_id={tool_exec.tool_call_id} error={error}")

    assert statuses == ["failed", "succeeded"], (
        "the failed first attempt and the succeeded retry must both be captured, in order"
    )
    assert len(call_ids) == 2, "each retry attempt must get its own tool_call_id"
    assert tool_executions[0].metadata.get("error_type") == "TimeoutError"

    execution_records = [record for record in records if isinstance(record, Execution)]
    print(
        f"\nFinal execution status: {execution_records[-1].status if execution_records else 'n/a'}"
    )
    assert execution_records[-1].status == "completed", (
        "the overall run still completes even though one tool attempt failed"
    )
    print(
        "\nKey finding: xgraph captures every retry attempt of a LangChain-retried tool "
        "as its own ToolExecution record (failed, then succeeded), all correlated under "
        "the same run_id/trace_id as the rest of the (multi-agent) execution -- so "
        "transient failures remain visible in the provenance trail even when the graph "
        "recovers and completes successfully."
    )


if __name__ == "__main__":
    asyncio.run(main())

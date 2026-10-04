"""Correlation across agents, and visible transient failures, in one run.

A researcher node calls a market-data tool that times out once and succeeds on the
retry configured with ``with_retry``; a writer node turns the finding into a report.
Both tool attempts are recorded as separate ``ToolExecution`` records (``timed_out``,
then ``succeeded``) and every record shares the run's ID and trace ID, so a recovered
failure stays visible even though the run completes.

Run with:

    uv run python examples/multi_agent_retry_correlation.py
"""

import asyncio
from typing import TypedDict

from _shared import show
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph

from langgraph_xai import ProvenanceStore, StoreFilter, XAIRuntime

attempts = {"count": 0}


@tool
def market_data(symbol: str) -> str:
    """Look up the latest market data for a ticker symbol."""
    attempts["count"] += 1
    if attempts["count"] == 1:
        raise TimeoutError("upstream quote service timed out")
    return f"{symbol}: last=142.10, change=+1.4%"


lookup = market_data.with_retry(stop_after_attempt=3, wait_exponential_jitter=False)


class Briefing(TypedDict, total=False):
    symbol: str
    research: str
    report: str


def researcher(state: Briefing) -> Briefing:
    return {"research": lookup.invoke({"symbol": state["symbol"]})}


def writer(state: Briefing) -> Briefing:
    return {"report": f"Daily brief for {state['symbol']}: {state['research']}"}


async def main() -> None:
    builder = StateGraph(Briefing)
    builder.add_node("researcher", researcher)
    builder.add_node("writer", writer)
    builder.add_edge(START, "researcher")
    builder.add_edge("researcher", "writer")
    builder.add_edge("writer", END)

    xai = XAIRuntime(application_id="research", tenant_id="demo", graph_id="daily-brief")
    with xai.collect_runs() as runs:
        result = await xai.instrument(builder.compile()).ainvoke(
            {"symbol": "ACME"}, {"metadata": {"trace_id": "brief-2026-10-04"}}
        )
    (run,) = runs
    print(result["report"])

    store = xai.registry.require(ProvenanceStore)
    records = [
        record
        async for record in store.query(
            StoreFilter(application_id="research", tenant_id="demo", run_id=run.run_id)
        )
    ]
    show(
        "Correlation",
        {
            "records": len(records),
            "run_ids": sorted({str(record.context.run_id) for record in records}),
            "trace_ids": sorted({str(record.context.trace_id) for record in records}),
        },
    )
    show(
        "Tool attempts",
        [
            {"status": item.status, "error_type": item.metadata.get("error_type")}
            for item in run.execution.tools
        ],
    )
    show("Nodes", [f"{node.node_id}: {node.status}" for node in run.execution.nodes])


if __name__ == "__main__":
    asyncio.run(main())

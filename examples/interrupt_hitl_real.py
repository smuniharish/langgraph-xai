"""Real human-in-the-loop verification: a genuine LangGraph ``interrupt()``/``Command(resume=...)``
cycle, instrumented end to end, with no manual bookkeeping by the caller.

Before this example was written, ``XAIRuntime`` had no way to observe a real
interrupt: LangGraph reports a pause through a special ``__interrupt__`` key in
its output rather than through LangChain's callback system, so an interrupted
run was silently recorded as ``ExecutionStatus.COMPLETED``. This example is the
regression check for the fix: instrumentation now detects the pause, records
an ``InterruptEvent``/``HumanInteraction``, and marks the execution
``ExecutionStatus.INTERRUPTED``; resuming with ``Command(resume=...)`` records
a matching ``HumanInteractionType.RESUME`` on the continuation run.

Run with:

    uv run python examples/interrupt_hitl_real.py
"""

import asyncio
import json

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from typing_extensions import TypedDict

from langgraph_xai import Execution, ExecutionStatus, HumanInteractionType, XAIRuntime
from langgraph_xai.core.protocols import ProvenanceStore
from langgraph_xai.storage.memory import StoreFilter


class WireTransferState(TypedDict, total=False):
    amount: float
    approved: bool


def human_review(state: WireTransferState) -> WireTransferState:
    decision = interrupt(
        {"question": f"Approve a ${state['amount']:,.0f} wire transfer?", "amount": state["amount"]}
    )
    return {"approved": bool(decision)}


async def main() -> None:
    builder = StateGraph(WireTransferState)
    builder.add_node("human_review", human_review)
    builder.add_edge(START, "human_review")
    builder.add_edge("human_review", END)
    graph = builder.compile(checkpointer=InMemorySaver())

    runtime = XAIRuntime(graph_id="wire-transfer-hitl")
    instrumented = runtime.instrument(graph)
    thread = {"configurable": {"thread_id": "wire-42"}}

    # 1. First invocation pauses at the real interrupt() call.
    paused = await instrumented.ainvoke({"amount": 9000.0}, thread)
    print("--- Output after the first invoke (graph is paused) ---")
    print(json.dumps({"has_interrupt_key": "__interrupt__" in paused}, indent=2))

    # 2. A human approves out-of-band, then the graph resumes.
    resumed = await instrumented.ainvoke(Command(resume=True), thread)
    print("\n--- Output after Command(resume=True) ---")
    print(json.dumps(resumed, indent=2))

    # 3. Inspect what xgraph actually captured, with no manual instrumentation.
    store = runtime.registry.get(ProvenanceStore)
    context = runtime.context_from_config()

    executions = [
        record
        async for record in store.query(
            StoreFilter(
                application_id=context.application_id,
                tenant_id=context.tenant_id,
                item_type=Execution,
                limit=50,
            )
        )
    ]
    print(f"\n--- {len(executions)} Execution records captured across the pause/resume cycle ---")
    for execution in executions:
        print(
            json.dumps(
                {
                    "status": str(execution.status),
                    "human_interactions": [
                        {
                            "interaction_type": str(item.interaction_type),
                            "request_reference": item.request_reference,
                            "metadata": item.metadata,
                        }
                        for item in execution.human_interactions
                    ],
                },
                indent=2,
                default=str,
            )
        )

    assert any(execution.status == ExecutionStatus.INTERRUPTED for execution in executions), (
        "the paused run must be recorded as INTERRUPTED, not COMPLETED"
    )
    assert any(
        interaction.interaction_type == HumanInteractionType.RESUME
        for execution in executions
        for interaction in execution.human_interactions
    ), "the resumed run must record a RESUME human interaction"
    print("\nVerified: interrupt and resume are both captured as first-class artifacts.")


if __name__ == "__main__":
    asyncio.run(main())

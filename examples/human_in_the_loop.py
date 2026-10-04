"""Human-in-the-loop: a LangGraph ``interrupt()`` pause and its ``Command(resume=...)``.

The paused call is recorded as an ``interrupted`` run with the reviewer's question,
and the resumed call as a second run that records the answer. Because the graph has a
checkpointer, both runs are linked to LangGraph checkpoints automatically: the paused
run to the checkpoint it stopped at, and the resumed run to the checkpoint it continued
from, with ``continuation_of`` naming the paused run. An approval recorded after the
run finished still reaches the stored record.

Run with:

    uv run python examples/human_in_the_loop.py
"""

import asyncio
from typing import TypedDict

from _shared import show
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from langgraph_xai import (
    Execution,
    HumanInteractionType,
    ProvenanceStore,
    StoreFilter,
    XAIRuntime,
)


class WireTransfer(TypedDict, total=False):
    amount: float
    approved: bool


def human_review(state: WireTransfer) -> WireTransfer:
    approved = interrupt(
        {"question": f"Approve a ${state['amount']:,.0f} wire transfer?", "amount": state["amount"]}
    )
    return {"approved": bool(approved)}


def describe(execution: Execution) -> dict[str, object]:
    return {
        "run_id": execution.context.run_id,
        "status": execution.status,
        "continuation_of": execution.continuation_of,
        "nodes": [f"{node.node_id}: {node.status}" for node in execution.nodes],
        "human_interactions": [
            {
                "type": item.interaction_type,
                "interrupt_id": item.request_reference,
                "actor": item.actor_reference,
                "payload": item.metadata.get("value"),
            }
            for item in execution.human_interactions
        ],
        "checkpoints": [
            {"checkpoint_id": item.checkpoint_id, "restored": item.restored}
            for item in execution.checkpoints
        ],
    }


async def main() -> None:
    builder = StateGraph(WireTransfer)
    builder.add_node("human_review", human_review)
    builder.add_edge(START, "human_review")
    builder.add_edge("human_review", END)

    xai = XAIRuntime(graph_id="wire-transfer")
    graph = xai.instrument(builder.compile(checkpointer=InMemorySaver()))
    thread = {"configurable": {"thread_id": "wire-42"}}

    with xai.collect_runs() as runs:
        paused = await graph.ainvoke({"amount": 9000.0}, thread)
        (question,) = paused["__interrupt__"]
        print(f"Paused on: {question.value['question']}")
        resumed = await graph.ainvoke(Command(resume=True), thread)
        print(f"Resumed: {resumed}")
    paused_run, resumed_run = runs

    # Recorded after the run finished, and still added to the stored record.
    await xai.record_human_interaction(
        HumanInteractionType.APPROVAL, actor_reference="reviewer:ana", run=resumed_run
    )

    show("Paused run", describe(paused_run.execution))
    show("Resumed run", describe(resumed_run.execution))

    store = xai.registry.require(ProvenanceStore)
    query = StoreFilter(
        application_id=xai.application_id,
        tenant_id=xai.tenant_id,
        run_id=resumed_run.run_id,
        item_type=Execution,
    )
    (stored,) = [item async for item in store.query(query) if isinstance(item, Execution)]
    show(
        "Stored record of the resumed run",
        {"human_interactions": [item.interaction_type for item in stored.human_interactions]},
    )


if __name__ == "__main__":
    asyncio.run(main())

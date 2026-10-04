"""The smallest instrumented graph: wrap it, run it, and inspect what was captured.

Run with:

    uv run python examples/minimal_langgraph.py
"""

import asyncio
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from langgraph_xai import XAIRuntime


class State(TypedDict, total=False):
    question: str
    answer: str


def answer(state: State) -> State:
    return {"answer": f"Echo: {state['question']}"}


async def main() -> None:
    builder = StateGraph(State)
    builder.add_node("answer", answer)
    builder.add_edge(START, "answer")
    builder.add_edge("answer", END)

    xai = XAIRuntime(graph_id="minimal")
    graph = xai.instrument(builder.compile())

    with xai.collect_runs() as runs:
        result = await graph.ainvoke({"question": "Why?"})

    execution = runs[0].execution
    print(result)
    print(f"status={execution.status} nodes={[node.node_id for node in execution.nodes]}")
    for transition in execution.state_transitions:
        for change in transition.changes:
            print(f"{transition.node_id}: {change.path} {change.before!r} -> {change.after!r}")


if __name__ == "__main__":
    asyncio.run(main())

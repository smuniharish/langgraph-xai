"""Checkpoint/continuation-shaped HITL example with a local approval."""

import asyncio

from _shared import compiled_graph, explain_result

from langgraph_xai import DecisionFactor, XAIRuntime


async def main() -> None:
    runtime = XAIRuntime(graph_id="hitl")
    result = await runtime.instrument(
        compiled_graph(lambda _: {"approved": True, "answer": "Approved by reviewer."})
    ).ainvoke({"approved": False})
    explanation = await explain_result(
        runtime,
        "APPROVED",
        DecisionFactor(name="human_approval", value=True),
    )
    print(result, explanation)


if __name__ == "__main__":
    asyncio.run(main())

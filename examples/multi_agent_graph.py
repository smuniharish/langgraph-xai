"""Provenance across two locally composed graph agents."""

import asyncio

from _shared import DemoState, explain_result
from langgraph.graph import END, START, StateGraph

from langgraph_xai import DecisionFactor, XAIRuntime


async def main() -> None:
    builder = StateGraph(DemoState)
    builder.add_node("researcher", lambda _: {"answer": "Structured finding"})
    builder.add_node("writer", lambda state: {"answer": f"Published: {state['answer']}"})
    builder.add_edge(START, "researcher")
    builder.add_edge("researcher", "writer")
    builder.add_edge("writer", END)
    runtime = XAIRuntime(graph_id="multi-agent")
    result = await runtime.instrument(builder.compile()).ainvoke({"query": "Explain XAI"})
    explanation = await explain_result(
        runtime,
        "PUBLISH_RESPONSE",
        DecisionFactor(name="research_complete", value=True),
    )
    print(result, explanation)


if __name__ == "__main__":
    asyncio.run(main())

"""Graph -> instrument -> execute -> explain."""

import asyncio

from _shared import compiled_graph, explain_result

from langgraph_xai import DecisionFactor, XAIRuntime


async def main() -> None:
    runtime = XAIRuntime(graph_id="minimal")
    graph = runtime.instrument(compiled_graph(lambda state: {"answer": f"Echo: {state['query']}"}))
    result = await graph.ainvoke({"query": "Why?"})
    explanation = await explain_result(
        runtime,
        "FINAL_RESPONSE",
        DecisionFactor(name="answer_available", value=True),
    )
    print(result)
    print(explanation)


if __name__ == "__main__":
    asyncio.run(main())

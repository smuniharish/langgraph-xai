"""Local customer-support routing with explicit decision factors."""

import asyncio

from _shared import compiled_graph, explain_result

from langgraph_xai import DecisionFactor, XAIRuntime


async def main() -> None:
    runtime = XAIRuntime(graph_id="customer-support")
    result = await runtime.instrument(
        compiled_graph(lambda _: {"answer": "Account specialist assigned."})
    ).ainvoke({"query": "My issue is still unresolved"})
    explanation = await explain_result(
        runtime,
        "ESCALATE_TO_SPECIALIST",
        DecisionFactor(name="unresolved_attempts", value=3),
    )
    print(result, explanation)


if __name__ == "__main__":
    asyncio.run(main())

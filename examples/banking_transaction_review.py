"""Policy-aware banking review example using structured observable factors."""

import asyncio

from _shared import compiled_graph, explain_result

from langgraph_xai import DecisionFactor, XAIRuntime


async def main() -> None:
    runtime = XAIRuntime(graph_id="banking-review")
    result = await runtime.instrument(
        compiled_graph(lambda _: {"risk_score": 0.91, "answer": "HUMAN_REVIEW"})
    ).ainvoke({"risk_score": 0.0})
    explanation = await explain_result(
        runtime,
        "HUMAN_REVIEW",
        DecisionFactor(name="fraud_risk_score", value=0.91, weight=0.8),
        DecisionFactor(name="review_threshold", value=0.8, weight=0.2),
    )
    print(result, explanation)


if __name__ == "__main__":
    asyncio.run(main())

"""A local retry followed by successful execution."""

import asyncio

from _shared import compiled_graph, explain_result

from langgraph_xai import DecisionFactor, XAIRuntime


async def main() -> None:
    attempts = 0

    def flaky(_):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TimeoutError("simulated transient failure")
        return {"attempts": attempts, "answer": "Recovered"}

    runtime = XAIRuntime(graph_id="retry")
    graph = compiled_graph(flaky).with_retry(stop_after_attempt=2)
    result = await runtime.instrument(graph).ainvoke({"attempts": 0})
    explanation = await explain_result(
        runtime,
        "RECOVERED",
        DecisionFactor(name="attempt_count", value=attempts),
    )
    print(result, explanation)


if __name__ == "__main__":
    asyncio.run(main())

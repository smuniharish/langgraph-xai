"""Tool selection and execution represented without provider credentials."""

import asyncio

from _shared import compiled_graph, explain_result

from langgraph_xai import DecisionFactor, ToolStatus, XAIRuntime


async def main() -> None:
    runtime = XAIRuntime(graph_id="tool-agent")
    run = await runtime.start_run()
    await runtime.record_tool("local_calculator", status=ToolStatus.SUCCEEDED, run=run)
    await runtime.finish_run(run)
    result = await runtime.instrument(compiled_graph(lambda _: {"answer": "42"})).ainvoke(
        {"query": "6 * 7"}
    )
    explanation = await explain_result(
        runtime,
        "USE_LOCAL_CALCULATOR",
        DecisionFactor(name="arithmetic_required", value=True),
    )
    print(result, explanation)


if __name__ == "__main__":
    asyncio.run(main())

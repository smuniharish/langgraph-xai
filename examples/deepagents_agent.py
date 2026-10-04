"""Instrument a ``deepagents`` deep agent with no framework-specific code.

``create_deep_agent`` adds planning, filesystem, and subagent middleware on top of
``create_agent``, but the result is still a compiled LangGraph graph, so the same
``XAIRuntime.instrument`` call captures the whole run: every node, state change, and
tool call, including those made by subagents, under one run ID.

Requires the ``examples`` dependency group and ``OPENAI_API_KEY`` (optionally
``OPENAI_BASE_URL`` and ``OPENAI_MODEL``).

Run with:

    uv run --group examples --extra llm-openai python examples/deepagents_agent.py
"""

import asyncio
from collections import Counter

from _shared import chat_model, show
from deepagents import create_deep_agent
from langchain_core.tools import tool

from langgraph_xai import XAIRuntime


@tool
def word_count(text: str) -> int:
    """Count the words in a piece of text."""
    return len(text.split())


async def main() -> None:
    xai = XAIRuntime(graph_id="deep-research")
    question = "Count the words in: explainability makes agents accountable."
    async with chat_model() as model:
        agent = create_deep_agent(
            model=model,
            tools=[word_count],
            system_prompt=(
                "You are a concise research assistant. Use the word_count tool on any text "
                "you are given, then report the count."
            ),
        )
        with xai.collect_runs() as runs:
            result = await xai.instrument(agent).ainvoke(
                {"messages": [{"role": "user", "content": question}]}
            )
    (run,) = runs
    execution = run.execution

    print(f"Agent: {result['messages'][-1].content}")
    show(
        "Captured for one run",
        {
            "run_id": run.run_id,
            "status": execution.status,
            "nodes": dict(Counter(node.node_id for node in execution.nodes)),
            "tools": [f"{item.tool_name}: {item.status}" for item in execution.tools],
            "state_transitions": len(execution.state_transitions),
        },
    )


if __name__ == "__main__":
    asyncio.run(main())

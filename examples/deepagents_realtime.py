"""Instrument a real ``deepagents`` deep agent with xgraph, using a real LLM.

deepagents (https://github.com/langchain-ai/deepagents) builds a compiled
LangGraph ``StateGraph`` on top of ``langchain.agents.create_agent`` --
adding planning/filesystem/subagent middleware -- but the result is still an
ordinary LangGraph runnable. This script proves xgraph needs zero
deepagents-specific code to instrument it: the same ``XAIRuntime.instrument``
call used everywhere else captures the whole run, including the
general-purpose subagent's own tool calls, under one correlated ``run_id``.

Run with:

    uv run --system-certs python examples/deepagents_realtime.py

Requires ``EXPLABS_API_KEY`` in the environment.
"""

import asyncio
import os

from deepagents import create_deep_agent
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from langgraph_xai import Execution, XAIRuntime
from langgraph_xai.core import XAIEvent
from langgraph_xai.core.protocols import ProvenanceStore
from langgraph_xai.storage.memory import StoreFilter


@tool
def word_count(text: str) -> int:
    """Count the words in a piece of text."""
    return len(text.split())


async def main() -> None:
    model = ChatOpenAI(
        base_url="https://api.experientiallabs.ai/v1",
        api_key=os.environ["EXPLABS_API_KEY"],
        model="gpt-5.6-luna",
    )

    agent = create_deep_agent(
        model=model,
        tools=[word_count],
        system_prompt=(
            "You are a concise research assistant. Use the word_count tool on "
            "any text you are given, then report the count."
        ),
    )

    runtime = XAIRuntime(
        application_id="docs-verification",
        tenant_id="xgraph-dev",
        graph_id="deepagents-word-counter",
    )
    instrumented = runtime.instrument(agent)

    result = await instrumented.ainvoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "Count the words in this sentence: xgraph explains LangGraph runs.",
                }
            ]
        }
    )
    final_message = result["messages"][-1].content
    print("--- Final agent message ---")
    print(final_message)

    store = runtime.registry.get(ProvenanceStore)
    context = runtime.context_from_config()
    records = [
        record
        async for record in store.query(
            StoreFilter(
                application_id=context.application_id, tenant_id=context.tenant_id, limit=200
            )
        )
    ]
    run_ids = {str(record.context.run_id) for record in records}
    kinds = [
        record.event_type if isinstance(record, XAIEvent) else type(record).__name__
        for record in records
    ]

    print(f"\n--- {len(records)} records captured across one deepagents run ---")
    for kind in kinds:
        print(" -", kind)
    print(f"\nDistinct run_ids: {run_ids}")

    execution_records = [record for record in records if isinstance(record, Execution)]
    assert len(run_ids) == 1, (
        "the whole deep-agent run (including any subagent work) must correlate"
    )
    assert execution_records, "at least one Execution record must be captured"
    assert execution_records[-1].status == "completed"
    print(
        "\nVerified: xgraph instrumented a real deepagents graph with no "
        "deepagents-specific code -- every internal tool call and state "
        "transition shares one run_id."
    )


if __name__ == "__main__":
    asyncio.run(main())

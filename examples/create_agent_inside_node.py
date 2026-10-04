"""Nest a ``create_agent`` agent inside one node of a larger LangGraph graph.

Only the outer three-node graph (``intake`` -> ``agent`` -> ``finalize``) is
instrumented. The ``agent`` node builds and invokes a ``create_agent`` agent; because
the current run travels with the call through context variables, the inner agent's
tool calls and the decision its middleware records attach to the outer run.

Requires ``OPENAI_API_KEY`` (optionally ``OPENAI_BASE_URL`` and ``OPENAI_MODEL``).

Run with:

    uv run --extra llm-openai python examples/create_agent_inside_node.py
"""

import asyncio
from typing import Any, TypedDict

from _shared import chat_model, show
from create_agent_decision_explanation import DecisionRecorder, check_fraud_risk
from langchain.agents import create_agent
from langgraph.graph import END, START, StateGraph

from langgraph_xai import Audience, XAIRuntime


class Review(TypedDict, total=False):
    query: str
    validated: bool
    answer: str


def build_graph(xai: XAIRuntime, model: Any):
    async def intake(state: Review) -> Review:
        return {"validated": bool(state.get("query"))}

    async def agent(state: Review) -> Review:
        inner = create_agent(
            model,
            tools=[check_fraud_risk],
            system_prompt="You are a fraud review assistant. Use the tool, then answer briefly.",
            middleware=[DecisionRecorder(xai)],
        )
        result = await inner.ainvoke({"messages": [{"role": "user", "content": state["query"]}]})
        return {"answer": result["messages"][-1].content}

    async def finalize(state: Review) -> Review:
        return {"answer": state["answer"].strip()}

    builder = StateGraph(Review)
    builder.add_node("intake", intake)
    builder.add_node("agent", agent)
    builder.add_node("finalize", finalize)
    builder.add_edge(START, "intake")
    builder.add_edge("intake", "agent")
    builder.add_edge("agent", "finalize")
    builder.add_edge("finalize", END)
    return builder.compile()


async def main() -> None:
    xai = XAIRuntime(graph_id="fraud-review-nested")
    async with chat_model() as model:
        graph = xai.instrument(build_graph(xai, model))
        with xai.collect_runs() as runs:
            result = await graph.ainvoke({"query": "Transaction txn-8841 is $9200. Is it risky?"})
    (run,) = runs

    print(f"Answer: {result['answer']}")
    show(
        "One run for the whole call",
        {
            "outer_nodes": [
                node.node_id for node in run.execution.nodes if node.parent_node_id is None
            ],
            "tool_calls": [item.tool_name for item in run.execution.tools],
            "decisions": [item.selected_action for item in run.decisions],
        },
    )
    explanation = await xai.explain_decision(run.decisions[-1], audience=Audience.END_USER, run=run)
    show("Explanation", explanation.model_dump(mode="json", include={"summary", "reasons"}))


if __name__ == "__main__":
    asyncio.run(main())

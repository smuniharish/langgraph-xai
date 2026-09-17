"""Nest a real ``create_agent`` agent inside a node of a larger LangGraph.

The [`create_agent_decision_explanation.py`](./create_agent_decision_explanation.py)
example instruments a ``create_agent`` agent directly -- the agent *is* the
whole compiled graph. That is not the only shape real applications take:
often a ``create_agent`` agent is one step of a larger, hand-written
``StateGraph`` -- for example, an "intake" node that validates/prepares
input, an "agent" node that delegates to an LLM agent to decide what to do,
and a "finalize" node that shapes the response.

This script builds exactly that: a three-node ``StateGraph`` where the
middle node constructs and calls a ``create_agent`` agent *inside its own
node function*. Only the outer graph is ever passed to
``runtime.instrument(...)`` -- the inner agent is never instrumented
directly, and is not even constructed until the node runs. That still
works correctly because ``XAIRuntime.current_run`` is tracked with a
``contextvars.ContextVar``: it stays set for the entire outer
``ainvoke(...)`` call, including every ``await`` inside every node,
however deeply nested -- so the inner agent's ``DecisionRecordingMiddleware``
records its ``Decision`` against the very same run the outer graph started.

Run with:

    uv run --system-certs python examples/create_agent_inside_node.py

Requires ``EXPLABS_API_KEY`` in the environment (the inner agent needs a
real model to decide whether to call a tool and to answer).
"""

import asyncio
import os
from typing import Any, TypedDict

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

from langgraph_xai import Decision, DecisionFactor, XAIRuntime
from langgraph_xai.core import ExplanationContext


@tool
def check_fraud_risk(transaction_id: str, amount: float) -> str:
    """Look up the fraud risk score for a transaction."""
    return "0.91" if amount > 5000 else "0.12"


class DecisionRecordingMiddleware(AgentMiddleware):
    """Records the inner agent's final answer as a `Decision` and explains it.

    Identical to the middleware in ``create_agent_decision_explanation.py``:
    the ``XAIRuntime`` is stored as ``self.xai_runtime`` (never ``self.runtime``)
    because ``aafter_model``'s own second parameter is reserved by LangGraph
    for its own injected ``Runtime`` context object under that exact name.
    """

    def __init__(self, xai_runtime: XAIRuntime) -> None:
        super().__init__()
        self.xai_runtime = xai_runtime
        self.decision: Decision | None = None
        self.explanation_summary: str | None = None

    async def aafter_model(self, state: dict[str, Any], runtime: Any) -> None:
        last_message = state["messages"][-1]
        if getattr(last_message, "tool_calls", None):
            return None  # still calling a tool; not a final decision yet

        self.decision = await self.xai_runtime.record_decision(
            "FINAL_RESPONSE",
            decision_type="final_response",
            factors=[DecisionFactor(name="answer_available", value=True)],
        )
        explanation = await self.xai_runtime.explain(
            ExplanationContext(
                execution=self.xai_runtime.current_run.execution,
                decision=self.decision,
                audience="end_user",
            )
        )
        self.explanation_summary = explanation.summary
        return None


class ReviewState(TypedDict, total=False):
    query: str
    validated: bool
    agent_answer: str
    decision_action: str
    explanation_summary: str


def build_review_graph(runtime: XAIRuntime, model: ChatOpenAI):
    """Build a 3-node StateGraph: intake -> agent -> finalize.

    The middle node is the only one that touches an LLM at all -- it builds
    a *fresh* create_agent agent and DecisionRecordingMiddleware every time
    it runs, and invokes that inner agent to completion before returning
    control to the outer graph.
    """

    async def intake(state: ReviewState) -> dict[str, Any]:
        # A real intake node would validate/normalize input; kept trivial
        # here since the point of this example is the nesting itself.
        return {"validated": bool(state.get("query"))}

    async def run_agent(state: ReviewState) -> dict[str, Any]:
        if not state.get("validated"):
            return {"agent_answer": "rejected: empty query"}

        middleware = DecisionRecordingMiddleware(runtime)
        inner_agent = create_agent(
            model,
            tools=[check_fraud_risk],
            system_prompt="You are a fraud review assistant. Use the tool, then answer briefly.",
            middleware=[middleware],
        )
        # The inner agent is invoked directly -- it is never itself passed
        # to runtime.instrument(...). Its middleware still records against
        # the outer run because XAIRuntime.current_run is a contextvar that
        # stays set for this whole outer ainvoke(...) call.
        result = await inner_agent.ainvoke(
            {"messages": [{"role": "user", "content": state["query"]}]}
        )
        return {
            "agent_answer": result["messages"][-1].content,
            "decision_action": middleware.decision.selected_action if middleware.decision else None,
            "explanation_summary": middleware.explanation_summary,
        }

    async def finalize(state: ReviewState) -> dict[str, Any]:
        return {"agent_answer": state["agent_answer"].strip()}

    builder = StateGraph(ReviewState)
    builder.add_node("intake", intake)
    builder.add_node("agent", run_agent)
    builder.add_node("finalize", finalize)
    builder.add_edge(START, "intake")
    builder.add_edge("intake", "agent")
    builder.add_edge("agent", "finalize")
    builder.add_edge("finalize", END)
    return builder.compile()


async def main() -> None:
    model = ChatOpenAI(
        base_url="https://api.experientiallabs.ai/v1",
        api_key=os.environ["EXPLABS_API_KEY"],
        model="gpt-5.6-luna",
    )
    runtime = XAIRuntime(graph_id="fraud-review-nested")
    graph = build_review_graph(runtime, model)

    instrumented = runtime.instrument(graph)
    result = await instrumented.ainvoke({"query": "Transaction txn-8841 is $9200. Is it risky?"})

    print("--- Outer graph result ---")
    print("agent_answer:", result["agent_answer"])
    print("decision_action:", result["decision_action"])
    print("explanation_summary:", result["explanation_summary"])

    assert result["decision_action"] == "FINAL_RESPONSE", (
        "the inner agent's middleware must have recorded its Decision against the outer run"
    )
    assert result["explanation_summary"], "explain() must have produced a summary"
    print(
        "\nVerified: a create_agent agent built and invoked *inside* a plain "
        "StateGraph node still records its Decision and Explanation onto the "
        "same run the outer runtime.instrument(...) call started -- no "
        "special-casing needed for the nesting."
    )


if __name__ == "__main__":
    asyncio.run(main())

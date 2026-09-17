"""Record and explain a decision from inside a real ``create_agent`` agent.

Most real LangGraph applications today are built with
``langchain.agents.create_agent`` rather than a hand-written ``StateGraph`` --
it still compiles to an ordinary LangGraph runnable, so
``XAIRuntime.instrument(...)`` needs no special-casing for it. The one
detail worth being deliberate about is *where* to hook in a decision: this
script uses ``create_agent``'s ``AgentMiddleware.aafter_model`` hook, which
fires once per model turn and lets you distinguish "the model just chose to
call a tool" from "the model produced a final answer" -- the latter is what
gets recorded as a `Decision` and explained.

A real gotcha this script deliberately avoids: the middleware hook's own
second parameter is itself named ``runtime`` (LangGraph injects its own
``Runtime[ContextT]`` context object under that name). Naming your
``XAIRuntime`` instance attribute anything other than that reserved
parameter name -- here, ``self.xai_runtime`` -- avoids silently shadowing it
inside the hook.

Run with:

    uv run --system-certs python examples/create_agent_decision_explanation.py

Requires ``EXPLABS_API_KEY`` in the environment (the agent itself needs a
real model to decide whether to call a tool and to answer).
"""

import asyncio
import os
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain.tools import tool
from langchain_openai import ChatOpenAI

from langgraph_xai import Decision, DecisionFactor, XAIRuntime
from langgraph_xai.core import ExplanationContext


@tool
def check_fraud_risk(transaction_id: str, amount: float) -> str:
    """Look up the fraud risk score for a transaction."""
    return "0.91" if amount > 5000 else "0.12"


class DecisionRecordingMiddleware(AgentMiddleware):
    """Records the agent's final answer as a `Decision` and explains it.

    Runs after every model turn; skips turns where the model is still
    calling a tool, and only records/explains once it produces a final
    answer with no further tool calls.
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


async def main() -> None:
    model = ChatOpenAI(
        base_url="https://api.experientiallabs.ai/v1",
        api_key=os.environ["EXPLABS_API_KEY"],
        model="gpt-5.6-luna",
    )
    runtime = XAIRuntime(graph_id="fraud-review")
    middleware = DecisionRecordingMiddleware(runtime)

    agent = create_agent(
        model,
        tools=[check_fraud_risk],
        system_prompt="You are a fraud review assistant. Use the tool, then answer briefly.",
        middleware=[middleware],
    )

    instrumented = runtime.instrument(agent)
    result = await instrumented.ainvoke(
        {"messages": [{"role": "user", "content": "Transaction txn-8841 is $9200. Is it risky?"}]}
    )

    print("--- Final agent message ---")
    print(result["messages"][-1].content)
    print("\n--- Recorded decision + explanation ---")
    print("selected_action:", middleware.decision.selected_action if middleware.decision else None)
    print("explanation:", middleware.explanation_summary)

    assert middleware.decision is not None, "the middleware must have recorded a Decision"
    assert middleware.decision.selected_action == "FINAL_RESPONSE"
    assert middleware.explanation_summary, "explain() must have produced a summary"
    print(
        "\nVerified: the Decision and Explanation were produced from inside "
        "create_agent's own after-model hook, with no canonical model built "
        "by hand in application code."
    )


if __name__ == "__main__":
    asyncio.run(main())

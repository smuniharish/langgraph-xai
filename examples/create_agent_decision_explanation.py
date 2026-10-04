"""Record and explain a decision from inside ``create_agent`` middleware.

``langchain.agents.create_agent`` compiles to an ordinary LangGraph graph, so
``XAIRuntime.instrument`` needs no special handling and every tool call is captured
automatically. ``AgentMiddleware.aafter_model`` runs after each model turn; once the
model answers without requesting another tool, the middleware records the tool
results the agent relied on as evidence and decides whether to escalate the case.

Requires ``OPENAI_API_KEY`` (optionally ``OPENAI_BASE_URL`` and ``OPENAI_MODEL``).

Run with:

    uv run --extra llm-openai python examples/create_agent_decision_explanation.py
"""

import asyncio
from typing import Any

from _shared import chat_model, show
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool

from langgraph_xai import Audience, DecisionFactor, DecisionType, EvidenceType, XAIRuntime


@tool
def check_fraud_risk(transaction_id: str, amount: float) -> str:
    """Look up the fraud risk score for a transaction."""
    return "0.91" if amount > 5000 else "0.12"


class DecisionRecorder(AgentMiddleware):
    """When the agent finishes, record its tool results as evidence and decide on escalation."""

    def __init__(self, xai: XAIRuntime, threshold: float = 0.8) -> None:
        super().__init__()
        self.xai = xai
        self.threshold = threshold

    async def aafter_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        messages = state["messages"]
        if getattr(messages[-1], "tool_calls", None):
            return None
        results = [message for message in messages if isinstance(message, ToolMessage)]
        evidence = [
            await self.xai.record_evidence(
                EvidenceType.TOOL_RESULT,
                summary=f"{message.name} returned {message.text}.",
                content_reference=f"tool-call://{message.tool_call_id}",
                confidence=1.0,
            )
            for message in results
        ]
        score = max((float(message.text) for message in results), default=0.0)
        await self.xai.record_decision(
            "ESCALATE_FOR_REVIEW" if score >= self.threshold else "NO_ACTION",
            decision_type=DecisionType.ESCALATION,
            candidate_actions=["ESCALATE_FOR_REVIEW", "NO_ACTION"],
            evidence_ids=[item.id for item in evidence],
            factors=[
                DecisionFactor(
                    name="fraud_risk_score",
                    value=score,
                    evidence_ids=[item.id for item in evidence],
                ),
                DecisionFactor(name="escalation_threshold", value=self.threshold),
            ],
        )
        return None


async def main() -> None:
    xai = XAIRuntime(graph_id="fraud-assistant")
    async with chat_model() as model:
        agent = create_agent(
            model,
            tools=[check_fraud_risk],
            system_prompt="You are a fraud review assistant. Use the tool, then answer briefly.",
            middleware=[DecisionRecorder(xai)],
        )
        with xai.collect_runs() as runs:
            result = await xai.instrument(agent).ainvoke(
                {
                    "messages": [
                        {"role": "user", "content": "Transaction txn-8841 is $9200. Is it risky?"}
                    ]
                }
            )
    (run,) = runs

    print(f"Agent: {result['messages'][-1].content}")
    show(
        "Captured tool calls",
        [
            {"tool": item.tool_name, "tool_call_id": item.tool_call_id, "status": item.status}
            for item in run.execution.tools
        ],
    )
    explanation = await xai.explain_decision(run.decisions[-1], audience=Audience.END_USER, run=run)
    show("Explanation", explanation.model_dump(mode="json", include={"summary", "reasons"}))


if __name__ == "__main__":
    asyncio.run(main())

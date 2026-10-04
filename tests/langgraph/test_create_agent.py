"""Capture of ``langchain.agents.create_agent`` agents, driven by a scripted model."""

from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from langgraph_xai import DecisionType, ExecutionStatus, ToolStatus, XAIRuntime


class ScriptedModel(GenericFakeChatModel):
    """Replays fixed messages and accepts tool binding like a real chat model."""

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedModel":
        return self


@tool
def check_fraud_risk(transaction_id: str) -> str:
    """Look up the fraud risk score for a transaction."""
    return "0.91"


class RecordDecision(AgentMiddleware):
    def __init__(self, xai: XAIRuntime) -> None:
        super().__init__()
        self.xai = xai

    async def aafter_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        if not getattr(state["messages"][-1], "tool_calls", None):
            await self.xai.record_decision("ESCALATE", decision_type=DecisionType.ESCALATION)


async def test_create_agent_runs_are_captured_end_to_end() -> None:
    model = ScriptedModel(
        messages=iter(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "check_fraud_risk",
                            "args": {"transaction_id": "t-1"},
                            "id": "call_a1",
                        }
                    ],
                ),
                AIMessage(content="High risk: 0.91."),
            ]
        )
    )
    xai = XAIRuntime()
    agent = create_agent(model, tools=[check_fraud_risk], middleware=[RecordDecision(xai)])

    with xai.collect_runs() as runs:
        result = await xai.instrument(agent).ainvoke(
            {"messages": [{"role": "user", "content": "risk?"}]}
        )
    (run,) = runs
    execution = run.execution

    assert result["messages"][-1].content == "High risk: 0.91."
    assert execution.status is ExecutionStatus.COMPLETED
    model_turns = [item for item in execution.state_transitions if item.node_id == "model"]
    assert len(model_turns) == 2
    assert all([change.path for change in turn.changes] == ["messages"] for turn in model_turns)
    (lookup,) = execution.tools
    assert (lookup.tool_name, lookup.tool_call_id, lookup.status) == (
        "check_fraud_risk",
        "call_a1",
        ToolStatus.SUCCEEDED,
    )
    assert [decision.selected_action for decision in run.decisions] == ["ESCALATE"]
    explanation = await xai.explain_decision(run.decisions[0], run=run)
    assert explanation.summary == "The escalation decision selected 'ESCALATE'."

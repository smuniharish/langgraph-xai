# create_agent decision

`create_agent` from LangChain compiles to an ordinary LangGraph graph, so
`xai.instrument` needs no special handling, and every tool call is captured. A
middleware records the decision once the model has answered. Source:
[`examples/create_agent_decision_explanation.py`](https://github.com/smuniharish/langgraph-xai/blob/master/examples/create_agent_decision_explanation.py).

```bash
export OPENAI_API_KEY=...
uv run python examples/create_agent_decision_explanation.py
```

## Recording the decision in middleware

`aafter_model` runs after each model turn. When the model answers without
requesting another tool, the middleware records the tool results as evidence
and decides whether to escalate:

```python
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
                summary=f"{message.name} returned {message.content}.",
                content_reference=f"tool-call://{message.tool_call_id}",
                confidence=1.0,
            )
            for message in results
        ]
        score = max((float(message.content) for message in results), default=0.0)
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
```

```python
agent = create_agent(
    chat_model(),
    tools=[check_fraud_risk],
    system_prompt="You are a fraud review assistant. Use the tool, then answer briefly.",
    middleware=[DecisionRecorder(xai)],
)

with xai.collect_runs() as runs:
    result = await xai.instrument(agent).ainvoke(
        {"messages": [{"role": "user", "content": "Transaction txn-8841 is $9200. Is it risky?"}]}
    )
```

## Output

Real output from a live OpenAI-compatible chat model:

```text
Agent: Yes—transaction **txn-8841** is high risk, with a fraud score of **0.91**.

--- Captured tool calls ---
[
  {
    "tool": "check_fraud_risk",
    "tool_call_id": "call_ustKSJ5Goitak8Mwu0rwRIHN",
    "status": "succeeded"
  }
]

--- Explanation ---
{
  "summary": "The escalation decision selected 'ESCALATE_FOR_REVIEW'.",
  "reasons": [
    "Selected action: ESCALATE_FOR_REVIEW.",
    "Alternatives considered: NO_ACTION.",
    "Factor escalation_threshold was 0.8.",
    "Factor fraud_risk_score was 0.91."
  ]
}
```

## What to notice

- **The decision is the application's, not the model's prose.** The model
  answered in natural language, but the escalation decision was recorded by
  code, from the tool result, against an explicit threshold.
- **The tool call is matched to the model's request** by `tool_call_id`.
- **Middleware is the natural place** to record decisions in agents whose
  control flow is the model's tool-calling loop.

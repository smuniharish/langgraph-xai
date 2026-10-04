# create_agent inside a node

A `create_agent` agent is built and invoked inside one node of a larger
three-node graph. Only the outer graph is instrumented, yet the inner agent's
tool calls and the decision its middleware records belong to the same run.
Source:
[`examples/create_agent_inside_node.py`](https://github.com/smuniharish/langgraph-xai/blob/master/examples/create_agent_inside_node.py).

```bash
export OPENAI_API_KEY=...
uv run python examples/create_agent_inside_node.py
```

## The graph

```python
async def agent(state: Review) -> Review:
    inner = create_agent(
        model,
        tools=[check_fraud_risk],
        system_prompt="You are a fraud review assistant. Use the tool, then answer briefly.",
        middleware=[DecisionRecorder(xai)],
    )
    result = await inner.ainvoke({"messages": [{"role": "user", "content": state["query"]}]})
    return {"answer": result["messages"][-1].content}
```

The outer graph runs `intake`, then `agent`, then `finalize`. `DecisionRecorder`
is the middleware from the [create_agent decision](create-agent.md) example.

## Output

Real output from a live OpenAI-compatible chat model:

```text
Answer: Yes—transaction **txn-8841** is high risk, with a fraud risk score of **0.91**.

--- One run for the whole call ---
{
  "outer_nodes": [
    "intake",
    "agent",
    "finalize"
  ],
  "tool_calls": [
    "check_fraud_risk"
  ],
  "decisions": [
    "ESCALATE_FOR_REVIEW"
  ]
}

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

- **One run for the whole call.** The inner agent was never instrumented, but
  its tool call and decision are in the outer run, because the current run
  travels with the call through context variables.
- **Inner nodes are attributed to their parent.** The agent's own `model` and
  `tools` nodes are recorded with `parent_node_id` set to `agent`. The output
  lists only top-level nodes.

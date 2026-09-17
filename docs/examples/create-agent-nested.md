# create_agent nested inside a StateGraph node

The [`create_agent` quickstart example](../getting-started/quickstart.md#build-a-real-agent-record-its-decision-and-explain-it)
instruments a `create_agent` agent directly — the agent *is* the whole
compiled graph. Real applications often nest it one level deeper: a
hand-written `StateGraph` with an `intake` node, an `agent` node that
delegates to an LLM agent, and a `finalize` node — with only the *outer*
graph ever passed to `runtime.instrument(...)`.

This verifies, with a real run rather than an inspection of source code,
that the inner agent's `Decision` and `Explanation` are recorded onto the
same run the outer `runtime.instrument(...)` call started — with **no**
special-casing for the nesting, because `XAIRuntime.current_run` is tracked
with a `contextvars.ContextVar` that stays set for the entire outer
`ainvoke(...)` call, including every `await` inside every node, however
deeply nested.

Source: [`examples/create_agent_inside_node.py`](https://github.com/samamuniharish/langgraph-xai/blob/main/examples/create_agent_inside_node.py).

```python
class ReviewState(TypedDict, total=False):
    query: str
    validated: bool
    agent_answer: str
    decision_action: str
    explanation_summary: str


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
    # The inner agent is invoked directly -- it is never itself passed to
    # runtime.instrument(...). Its middleware still records against the
    # outer run because XAIRuntime.current_run is a contextvar that stays
    # set for this whole outer ainvoke(...) call.
    result = await inner_agent.ainvoke({"messages": [{"role": "user", "content": state["query"]}]})
    return {
        "agent_answer": result["messages"][-1].content,
        "decision_action": middleware.decision.selected_action if middleware.decision else None,
        "explanation_summary": middleware.explanation_summary,
    }


builder = StateGraph(ReviewState)
builder.add_node("intake", intake)
builder.add_node("agent", run_agent)
builder.add_node("finalize", finalize)
builder.add_edge(START, "intake")
builder.add_edge("intake", "agent")
builder.add_edge("agent", "finalize")
builder.add_edge("finalize", END)
graph = builder.compile()

instrumented = runtime.instrument(graph)
result = await instrumented.ainvoke({"query": "Transaction txn-8841 is $9200. Is it risky?"})
```

```bash
$ uv run --system-certs python examples/create_agent_inside_node.py
--- Outer graph result ---
agent_answer: Yes, this transaction is high risk, with a fraud risk score of 0.91.
decision_action: FINAL_RESPONSE
explanation_summary: The end_user explanation is based on the selected action 'FINAL_RESPONSE'.

Verified: a create_agent agent built and invoked *inside* a plain
StateGraph node still records its Decision and Explanation onto the same
run the outer runtime.instrument(...) call started -- no special-casing
needed for the nesting.
```

The agent's own free-text reply is model-generated and its exact wording
will vary between calls; `decision_action` and `explanation_summary` are
what xgraph itself records and reproduces exactly. The script asserts this
directly:

```python
assert result["decision_action"] == "FINAL_RESPONSE"
assert result["explanation_summary"]
```

## Why this matters

xgraph never requires the LLM agent itself to be the top-level compiled
graph. Whether `create_agent` is the entire graph or one step nested inside
a larger `StateGraph` — or nested inside a subgraph, inside a tool call,
or behind several layers of plain async functions — the same rule applies:
instrument the outermost graph once, and every `record_*`/`explain(...)`
call made anywhere underneath it during that call is correlated onto the
same run automatically.

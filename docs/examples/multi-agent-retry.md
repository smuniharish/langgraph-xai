# Multi-agent correlation, retries, and failures

A supervisor graph with two agent-like nodes (`researcher`, `writer`) and a
tool that fails once and recovers via LangChain's built-in `.with_retry()`.
This verifies, with real captured records rather than an inspection of
source code, that:

1. every artifact from **both** agents and **every retry attempt** shares one
   `run_id`/`trace_id`, and
2. the failed attempt is never silently lost — it is captured as its own
   `ToolExecution` record with `status="failed"`, distinct from the
   succeeded retry, even though the overall run still completes.

Source: [`examples/multi_agent_retry_correlation.py`](https://github.com/samamuniharish/langgraph-xai/blob/main/examples/multi_agent_retry_correlation.py).

```python
@tool
def flaky_market_data_lookup(symbol: str) -> str:
    """Look up market data for a symbol; fails transiently on the first call."""
    global _attempts
    _attempts += 1
    if _attempts == 1:
        raise TimeoutError("simulated transient upstream timeout")
    return f"{symbol}: last=142.10, change=+1.4%"


retrying_tool = flaky_market_data_lookup.with_retry(stop_after_attempt=3)


def researcher(state, config: RunnableConfig):
    finding = retrying_tool.invoke({"symbol": state["symbol"]}, config=config)
    return {"research": finding}


def writer(state):
    return {"report": f"Daily brief for {state['symbol']}: {state['research']}"}


builder = StateGraph(SupervisorState)
builder.add_node("researcher", researcher)
builder.add_node("writer", writer)
builder.add_edge(START, "researcher")
builder.add_edge("researcher", "writer")
builder.add_edge("writer", END)
```

!!! note "Propagate `config` into tool calls made from plain node functions"
    LangGraph only auto-injects the run's `RunnableConfig` (and therefore
    xgraph's callback handler) into a node function if that function declares
    a `config` parameter and forwards it explicitly to any `Runnable.invoke()`
    call it makes. Forgetting this is the single most common reason a tool
    call silently goes uncaptured in a custom node.

```bash
uv run python examples/multi_agent_retry_correlation.py
```

## Real captured records

```text
8 records captured; distinct run_ids={'292892d6-...'}; trace_ids={'multi-agent-retry-demo-0001'}
 - Execution
 - execution.started
 - tool.execution
 - tool.execution
 - state.transition
 - state.transition
 - state.transition
 - execution.completed

--- Tool attempts captured for the flaky tool ---
 - status=<ToolStatus.FAILED: 'failed'> tool_call_id=01a0aeba-3175-... error=TimeoutError
 - status=<ToolStatus.SUCCEEDED: 'succeeded'> tool_call_id=01a0aeba-365e-... error=None

Final execution status: completed
```

Both the failed attempt and the succeeded retry are captured as distinct
`ToolExecution` records, each with its own `tool_call_id`, both under the
**same** `run_id`. The script asserts this ordering and shape directly:

```python
assert statuses == ["failed", "succeeded"]
assert len(call_ids) == 2
assert tool_executions[0].metadata.get("error_type") == "TimeoutError"
assert execution_records[-1].status == "completed"
```

## Why this matters

Transient failures that a retry policy successfully recovers from are easy
to lose entirely from an observability trail — the naive view is "it
succeeded, nothing to see here". xgraph's per-call capture means the
first-attempt failure remains a first-class, queryable artifact even though
the run, correctly, still reports success.

# Multi-agent retries and correlation

A researcher node calls a market-data tool that times out once and succeeds on
retry, and a writer node turns the result into a report. Both tool attempts are
recorded, and every record shares one run ID and one trace ID. Source:
[`examples/multi_agent_retry_correlation.py`](https://github.com/smuniharish/langgraph-xai/blob/master/examples/multi_agent_retry_correlation.py).

```bash
uv run python examples/multi_agent_retry_correlation.py
```

## The graph

```python
@tool
def market_data(symbol: str) -> str:
    """Look up the latest market data for a ticker symbol."""
    attempts["count"] += 1
    if attempts["count"] == 1:
        raise TimeoutError("upstream quote service timed out")
    return f"{symbol}: last=142.10, change=+1.4%"


lookup = market_data.with_retry(stop_after_attempt=3, wait_exponential_jitter=False)


def researcher(state: Briefing) -> Briefing:
    return {"research": lookup.invoke({"symbol": state["symbol"]})}


def writer(state: Briefing) -> Briefing:
    return {"report": f"Daily brief for {state['symbol']}: {state['research']}"}
```

The call passes a trace ID, and every stored record of the run is then queried:

```python
with xai.collect_runs() as runs:
    result = await xai.instrument(builder.compile()).ainvoke(
        {"symbol": "ACME"}, {"metadata": {"trace_id": "brief-2026-10-04"}}
    )
(run,) = runs

store = xai.registry.require(ProvenanceStore)
records = [
    record
    async for record in store.query(
        StoreFilter(application_id="research", tenant_id="demo", run_id=run.run_id)
    )
]
```

## Output

```text
Daily brief for ACME: ACME: last=142.10, change=+1.4%

--- Correlation ---
{
  "records": 9,
  "run_ids": [
    "79751d55-01a5-40a3-b26d-2000a7a18951"
  ],
  "trace_ids": [
    "brief-2026-10-04"
  ]
}

--- Tool attempts ---
[
  {
    "status": "timed_out",
    "error_type": "TimeoutError"
  },
  {
    "status": "succeeded",
    "error_type": null
  }
]

--- Nodes ---
[
  "researcher: completed",
  "writer: completed"
]
```

## What to notice

- **A recovered failure stays visible.** The run completed, but the timed-out
  first attempt is recorded next to the successful retry, with its error type.
- **One identity for everything.** All nine stored records share the run ID and
  the trace ID passed in the config. A tracing backend can join them through
  the `xai.run_id` and `xai.trace_id` attributes.
- See [Correlate multi-agent runs and retries](../how-to/multi-agent.md) for
  node retries, nested agents, and correlation across services.

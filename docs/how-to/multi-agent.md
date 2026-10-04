# Correlate multi-agent runs and retries

A request often passes through several agents, subgraphs, retries, and services.
`langgraph-xai` gives everything one call produces a shared identity, so you
can collect it with one query.

## One call, one run, one identity

Every record of an instrumented call carries the same `ExecutionContext`.
`run_id` is unique per call. `thread_id` and `trace_id` come from the config
you pass:

```python
result = await graph.ainvoke(
    {"symbol": "ACME"},
    {"metadata": {"trace_id": "brief-2026-10-04"}, "configurable": {"thread_id": "desk-7"}},
)
```

Subgraphs, agents built with `create_agent` and called inside a node, and
`deepagents` sub-agents run inside the same call. Their nodes, tools, and state
changes therefore land in the same run. Subgraph nodes record the calling node
as `parent_node_id`. See
[create_agent inside a node](../examples/create-agent-nested.md) for real
output.

To join runs with your own request IDs, pass a UUID as
`metadata["xai_run_id"]`. The run then uses it instead of a random ID.

## Retries stay visible

A failure that a retry recovers from is still a fact worth keeping. Tool retries
(`tool.with_retry(...)`) record one `ToolExecution` per attempt. Node retries
(LangGraph's `RetryPolicy`) record one `NodeExecution` per attempt, numbered by
`attempt`.

The [multi-agent example](../examples/multi-agent-retry.md) runs a researcher
whose market-data tool times out once, then succeeds on retry, and a writer
that turns the result into a report:

```python
lookup = market_data.with_retry(stop_after_attempt=3, wait_exponential_jitter=False)
```

Real output:

```json
{
  "records": 9,
  "run_ids": ["79751d55-01a5-40a3-b26d-2000a7a18951"],
  "trace_ids": ["brief-2026-10-04"]
}
```

```json
[
  {"status": "timed_out", "error_type": "TimeoutError"},
  {"status": "succeeded", "error_type": null}
]
```

All nine stored records share one run ID and one trace ID, and the recovered
timeout is recorded next to the successful retry.

## Query everything a run produced

```python
store = xai.registry.require(ProvenanceStore)
records = [
    record
    async for record in store.query(
        StoreFilter(application_id="research", tenant_id="demo", run_id=run.run_id)
    )
]
```

Results are ordered by timestamp and event sequence. Add `item_type=` to
select one record type (for example `Execution` or `ToolExecutionEvent`), and
use `limit`/`offset` to page through long runs.

## Across services

When agents run in different processes, give them the same `trace_id` (and,
if they share an identity, the same `xai_run_id`). Each process records its own
runs, and the observability adapters export the identifiers as `xai.run_id`,
`xai.trace_id`, `xai.thread_id`, and `xai.tenant_id` attributes. Your tracing
backend can then join them; see [Observability](../architecture/observability.md).

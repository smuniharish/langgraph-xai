# Execution

## Kid-level view

Execution is the play-by-play: which graph run and node happened, in what
order, and when.

## Production view

An execution record identifies a run, parent/child boundary, node or event
kind, sequence, status, and correlation identifiers. It should be stable
enough to join artifacts without copying full graph state.

## Why and architecture

The runtime observes supported LangGraph boundaries and emits execution
records; the canonical model then links evidence and decisions to those
records. This keeps execution facts separate from interpretation.

## Real example: input and output

Automatic instrumentation (`runtime.instrument(graph)`) populates this
record for you on every `ainvoke`/`astream` call. The snippet below shows the
same shape built explicitly with the recording API, to make the input/output
correspondence clear:

```python
run = await runtime.start_run({"metadata": {"trace_id": "trace-8841"}})
await runtime.record_state_delta(
    "score_transaction", {"risk_score": 0.0}, {"risk_score": 0.91}, run=run
)
await runtime.record_tool(
    "fraud_detector",
    status="succeeded",
    latency_ms=42.5,
    output_reference="fraud-detector://run/8841/score",
    run=run,
)
await runtime.finish_run(run)
```

Real captured `Execution`, produced by
[`examples/canonical_model_gallery.py`](https://github.com/samamuniharish/langgraph-xai/blob/main/examples/canonical_model_gallery.py):

```json
{
  "schema_version": "1.0.0",
  "context": {
    "schema_version": "1.0.0",
    "application_id": "application",
    "tenant_id": "default",
    "graph_id": "fraud-review",
    "run_id": "399cf04f-e561-443d-a183-06775e05edd2",
    "trace_id": "trace-8841",
    "metadata": { "trace_id": "trace-8841" }
  },
  "status": "completed",
  "started_at": "2026-09-17T10:13:29.587563Z",
  "ended_at": "2026-09-17T10:13:29.588039Z",
  "nodes": [],
  "state_transitions": [
    {
      "node_id": "score_transaction",
      "changes": [{ "path": "risk_score", "before": 0.0, "after": 0.91 }],
      "capture_mode": "delta"
    }
  ],
  "tools": [
    {
      "tool_id": "fraud_detector",
      "tool_name": "fraud_detector",
      "status": "succeeded",
      "output_reference": "fraud-detector://run/8841/score",
      "retry_count": 0,
      "latency_ms": 42.5
    }
  ],
  "retrievals": [],
  "memory": [],
  "checkpoints": [],
  "human_interactions": [],
  "exceptions": []
}
```

(Fields trimmed for brevity are repeated nested `context`/`schema_version`
values, identical to the top-level ones shown above.)

## Mistakes to avoid

Use a run ID plus node ID and an explicit `completed` event. Avoid relying on
wall-clock order alone, recording arbitrary state blobs, or claiming that an
observed event explains causality.



# Langfuse

## Kid-level view

Langfuse can help inspect telemetry. It is not the rulebook for what an
explanation is allowed to say.

## Production view

An optional adapter may correlate policy-approved artifact IDs or summaries
with Langfuse traces. Credentials, endpoint, retention, and access controls
are configured for the Langfuse SDK/host; core runtime configuration remains
explicit and provider-neutral.

## Register the adapter

```python
from langfuse import Langfuse
from langgraph_xai import XAIRuntime
from langgraph_xai.core.protocols import ObservabilityProvider
from langgraph_xai.observability import LangfuseObservability

runtime = XAIRuntime(graph_id="fraud-review")
runtime.register(ObservabilityProvider, LangfuseObservability(Langfuse()))

graph = runtime.instrument(compiled_graph)
result = await graph.ainvoke({"transaction_id": "tx_9182"})

await runtime.flush()  # Langfuse buffers; flush before process exit
```

Requires the `langfuse` extra: `uv add "langgraph-xai[langfuse]"`.

## What actually gets sent

Every canonical event (`ExecutionStartedEvent`, `ToolExecutionEvent`,
`StateTransitionEvent`, …) becomes one Langfuse span via
`start_as_current_observation(name=event.event_type, ...)`, with:

- `metadata` set to the event's correlation fields (`run_id`, `trace_id`,
  `application_id`, `tenant_id`);
- `input` set to the event's canonical JSON payload;
- `trace_context={"trace_id": ...}` when the event carries one, so xgraph's
  spans nest under the same Langfuse trace as your LangChain/LangGraph
  callback-based traces, rather than starting a separate one.

Older Langfuse SDKs without `start_as_current_observation` fall back to
`client.create_event(...)` automatically — no configuration required.

## Common mistakes

Do not export canonical payloads merely because a Langfuse exporter is
enabled, or assume trace fields are evidence. `runtime.record_*(...)` calls
run every `metadata` mapping through the same credential-minimizing
sanitizer used for state capture (see [Policy providers](../api/policy.md)),
but that sanitizer only strips a fixed list of credential-shaped key names —
it is not a general PII filter, so avoid putting sensitive content in
`metadata` values themselves.


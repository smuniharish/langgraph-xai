# LangSmith

## Kid-level view

LangSmith traces what your LangChain/LangGraph code did. xgraph's
`LangSmithObservability` adapter sends its own canonical events into that
same trace tree — it does not replace LangSmith's own tracing.

## Production view

See [LangSmith comparison](langsmith-vs-langgraph-xai.md) for the precise
division of responsibility: LangSmith owns tracing/debugging/evaluation of
LangChain/LangGraph runs; xgraph owns the explainability semantic layer
(evidence, decisions, attribution, policy-filtered explanations) that a
trace alone does not capture.

## Register the adapter

```python
from langsmith import Client
from langgraph_xai import XAIRuntime
from langgraph_xai.core.protocols import ObservabilityProvider
from langgraph_xai.observability import LangSmithObservability

runtime = XAIRuntime(graph_id="fraud-review")
runtime.register(
    ObservabilityProvider,
    LangSmithObservability(Client(), project_name="fraud-review"),
)

graph = runtime.instrument(compiled_graph)
result = await graph.ainvoke({"transaction_id": "tx_9182"})

await runtime.flush()
```

Requires the `langsmith` extra: `uv add "langgraph-xai[langsmith]"`.

## What actually gets sent

Every canonical event becomes one LangSmith run
(`client.create_run(name=event.event_type, run_type="chain", ...)`), with
`trace_id`/`parent_run_id` carried over from the event's
`ExecutionContext` so xgraph's runs correlate with (rather than duplicate)
LangSmith's own automatic tracing of the underlying LangGraph execution.

## Common mistakes

Do not rely on this adapter to reconstruct evidence/decision/attribution
records after the fact from a LangSmith trace — record those explicitly
with `runtime.record_evidence(...)`/`runtime.record_decision(...)`; the
observability adapter only mirrors canonical events, it does not derive them.

# Runtime

The runtime coordinates capture, storage, attribution, policy, and explanation
for one application. See [Runtime architecture](../architecture/runtime.md) for
how runs, context propagation, concurrency, and failures work.

```python
from langgraph_xai import XAIRuntime

xai = XAIRuntime(application_id="payments", tenant_id="acme-bank", graph_id="fraud-review")
graph = xai.instrument(compiled_graph)
```

## XAIRuntime

::: langgraph_xai.runtime.runtime.XAIRuntime

## Run

::: langgraph_xai.runtime.runtime.Run

## XAIInstrumentationError

::: langgraph_xai.runtime.runtime.XAIInstrumentationError

## Registry

::: langgraph_xai.runtime.registry.Registry

## Instrumentation

::: langgraph_xai.instrumentation.graph.InstrumentedGraph

## Run ID metadata key

::: langgraph_xai.runtime.runtime.RUN_ID_METADATA_KEY

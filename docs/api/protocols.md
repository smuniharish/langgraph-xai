# Capabilities

The runtime resolves each capability through its `Registry`. Storage is an
abstract base class; the other capabilities are protocols that a provider
satisfies structurally. See [Extensibility](../architecture/plugins.md) for the
contracts each provider must keep.

```python
from langgraph_xai import PolicyProvider, ProvenanceStore

xai.register(ProvenanceStore, MyDatabaseStore())
xai.register(PolicyProvider, MyPolicy())
```

## Storage

::: langgraph_xai.core.protocols.ProvenanceStore

::: langgraph_xai.core.protocols.StoreQuery

## Observability

::: langgraph_xai.core.protocols.ObservabilityProvider

## Policies

::: langgraph_xai.core.protocols.CapturePolicy

::: langgraph_xai.core.protocols.PolicyProvider

## Attribution and explanation

::: langgraph_xai.core.protocols.AttributionEngine

::: langgraph_xai.core.protocols.ExplanationEngine

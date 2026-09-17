# Protocols

Every capability xgraph consumes â€” storage, telemetry, attribution,
explanation, policy â€” is a `typing.Protocol`. `XAIRuntime` only ever calls
these methods; it never checks which concrete class implements them. Adding
a new provider means writing a class that satisfies the protocol and
registering it â€” the runtime itself never changes.

```python
from langgraph_xai.core.protocols import ProvenanceStore


class PostgresProvenanceStore:
    """Satisfies ProvenanceStore structurally â€” no base class required."""

    async def write(self, item): ...
    async def get(self, entity_id): ...
    def query(self, query): ...
    async def parents(self, entity_id, *, context): ...
    async def children(self, entity_id, *, context): ...
    async def lineage(self, entity_id, *, context, max_depth=100): ...
    async def close(self): ...


runtime.register(ProvenanceStore, PostgresProvenanceStore(pool))
```

Because every protocol is `@runtime_checkable`, `isinstance(obj, ProvenanceStore)`
works for a fast sanity check, but structural typing (not the check) is what
the runtime actually relies on.

## Reference

::: langgraph_xai.core.protocols.ProvenanceStore

::: langgraph_xai.core.protocols.ObservabilityProvider

::: langgraph_xai.core.protocols.AttributionEngine

::: langgraph_xai.core.protocols.ExplanationEngine

::: langgraph_xai.core.protocols.PolicyProvider

::: langgraph_xai.core.protocols.CapturePolicy

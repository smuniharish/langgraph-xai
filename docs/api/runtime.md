# Runtime

`XAIRuntime` is the single entry point applications use: instrument a graph,
record explicit evidence/decisions, and assemble policy-filtered
explanations. One runtime instance owns one set of registered capabilities
and one `XAIConfig`; construct a separate runtime per tenant, per test, or
per graph rather than sharing global state.

## Construct and instrument

```python
from langgraph_xai import XAIRuntime

runtime = XAIRuntime(graph_id="fraud-review")
graph = runtime.instrument(compiled_graph)  # wraps invoke/ainvoke/stream/...

result = await graph.ainvoke({"transaction_id": "tx_9182"})
```

`instrument(...)` requires no other setup — every capability
(`ProvenanceStore`, `ObservabilityProvider`, `AttributionEngine`,
`ExplanationEngine`, `PolicyProvider`, `CapturePolicy`) already has a
working in-memory/no-op default. Replace one with `register(...)`:

```python
from langgraph_xai.core.protocols import ProvenanceStore
from langgraph_xai.storage import InMemoryProvenanceStore

runtime.register(ProvenanceStore, InMemoryProvenanceStore())
```

## Record explicit artifacts

Instrumentation captures graph/tool/state activity automatically. Your
application still records its own evidence and decisions:

```python
evidence = await runtime.record_evidence(
    "tool_result",
    summary="Fraud detector scored the transaction 0.91 (high risk).",
    confidence=0.9,
)
decision = await runtime.record_decision(
    "HUMAN_REVIEW",
    decision_type="routing",
    evidence_ids=[evidence.evidence_id],
)
```

## Assemble an explanation

```python
from langgraph_xai.core.models import ExplanationContext

explanation = await runtime.explain(
    ExplanationContext(execution=execution, decision=decision, audience="auditor")
)
```

See [Concepts: Explanations](../concepts/explanations.md) for the full real
JSON this produces, and [Configure failure modes](../how-to/failure-modes.md)
for what happens when a registered provider fails mid-call.

## Reference

::: langgraph_xai.runtime.XAIRuntime
    options:
      members:
        - register
        - instrument
        - context_from_config
        - start_run
        - finish_run
        - record_human_interaction
        - record_state_delta
        - record_evidence
        - record_decision
        - record_tool
        - record_retrieval
        - record_memory
        - record_provenance
        - record_artifact
        - attribute
        - explain
        - flush
        - close
        - run_sync
        - errors
        - current_run
        - is_instrumenting

::: langgraph_xai.runtime.Registry

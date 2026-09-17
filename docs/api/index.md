# API overview

The API reference is organized like LangGraph's and LangChain's: one focused
page per module, each combining a short real usage snippet with the
generated signature/docstring reference for that module's public classes.

| Page | What it covers |
| ---- | ---- |
| [Configuration](config.md) | `XAIConfig` — every field, its type, default, and when to change it |
| [Runtime](runtime.md) | `XAIRuntime` — the constructor and every `record_*`/`explain`/`instrument` method |
| [Canonical models](models.md) | `Execution`, `Evidence`, `Decision`, `ProvenanceLink`, `AttributionResult`, `Explanation`, and their nested types |
| [Protocols](protocols.md) | The `Protocol` interfaces a new provider must implement: `ProvenanceStore`, `ObservabilityProvider`, `AttributionEngine`, `ExplanationEngine`, `PolicyProvider`, `CapturePolicy` |
| [Storage](storage.md) | `InMemoryProvenanceStore` and the provenance-store contract |
| [Observability](observability.md) | `NoOpObservability`, `LangfuseObservability`, `OpenTelemetryObservability`, `LangSmithObservability` |
| [Explanation engines](explanation.md) | `StructuredExplanationEngine` and the `ExplanationEngine` contract |
| [Attribution engines](attribution.md) | `HybridAttribution` and the `AttributionEngine` contract |
| [Policy providers](policy.md) | `DefaultPolicyProvider`, `DefaultCapturePolicy` |

## Compatibility guidance

Treat every serialized canonical model (`Execution`, `Evidence`, `Decision`,
`ProvenanceLink`, `AttributionResult`, `Explanation`, …) as a versioned
contract identified by its `schema_version` field. Provider SDK objects
(a Langfuse client, an OTel tracer) passed into an adapter are not part of
xgraph's public contract — only the adapter class itself is. When a method
is marked planned in release notes, treat this reference as architectural
guidance rather than an availability guarantee for that release.

